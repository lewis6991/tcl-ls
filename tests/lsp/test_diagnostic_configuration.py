from pathlib import Path

import pytest

from tcl_lsp.checker import check_project, main
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.navigation import definition
from tests.lsp_support import wait_for_project_diagnostics


def _open_diagnostics(server: LanguageServer, path: Path) -> list[tuple[str, str]]:
    diagnostics = server.open_document(path.as_uri(), path.read_text(), 1)
    return sorted((item.code, item.severity) for item in diagnostics)


@pytest.mark.parametrize('severity', ['default', 'information', 'off'])
def test_unused_private_procedures_agree_in_editor_and_checker(
    tmp_path: Path, severity: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(f'diagnostic unused-proc {severity}\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        '# tcl-ls: diagnostic unused-proc off\n'
        'proc _ignored {} {}\n'
        'proc _unused {} {}\n'
        'proc public {} {}\n'
    )
    expected = (
        []
        if severity == 'off'
        else [('unused-proc', 'hint' if severity == 'default' else severity)]
    )
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == []
        wait_for_project_diagnostics(server)
        assert [
            (d.code, d.severity) for d in server.documents[source.as_uri()].analysis.diagnostics
        ] == expected
        assert [
            (d.diagnostic.code, d.diagnostic.severity)
            for d in check_project(source, threads=1).diagnostics
        ] == expected

        moved = '\n' + source.read_text()
        diagnostics = server.change_document(source.as_uri(), moved, 2)
        assert diagnostics == ()
        wait_for_project_diagnostics(server)
        diagnostics = server.documents[source.as_uri()].analysis.diagnostics
        assert [(d.code, d.severity) for d in diagnostics] == expected
        if diagnostics:
            assert diagnostics[0].span.start.line == 3
            assert diagnostics[0].tags == ('unnecessary',)
        assert server.change_document(source.as_uri(), moved + '_unused\n', 3) == ()
    finally:
        server.shutdown()


def test_private_procedure_hints_follow_calls_in_a_loaded_file(tmp_path: Path) -> None:
    helper = tmp_path / 'helper.tcl'
    helper.write_text('namespace eval app {proc _helper {} {}}\n')
    source = tmp_path / 'main.tcl'
    text = 'source [file join [file dirname [info script]] helper.tcl]\n::app::_helper\n'
    source.write_text(text)
    server = LanguageServer()
    try:
        assert server.open_document(source.as_uri(), text, 1) == ()
        assert server.open_document(helper.as_uri(), helper.read_text(), 1) == ()
        assert server.documents[helper.as_uri()].analysis.diagnostics == ()
        assert check_project(tmp_path, threads=1).diagnostics == ()

        changed = text.replace('::app::_helper\n', '')
        assert server.change_document(source.as_uri(), changed, 2) == ()
        wait_for_project_diagnostics(server)
        assert [d.code for d in server.documents[helper.as_uri()].analysis.diagnostics] == [
            'unused-proc'
        ]
        source.write_text(changed)
        assert [d.diagnostic.code for d in check_project(tmp_path, threads=1).diagnostics] == [
            'unused-proc'
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize('severity', ['default', 'information', 'off'])
def test_unused_variables_agree_in_editor_and_checker(tmp_path: Path, severity: str) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(f'diagnostic unused-variable {severity}\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'proc example {argument} {\n'
        '    # tcl-ls: diagnostic unused-variable off\n'
        '    variable ignored\n'
        '    variable version\n'
        '}\n'
    )
    expected = (
        []
        if severity == 'off'
        else [('unused-variable', 'hint' if severity == 'default' else severity)] * 2
    )
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == expected
        report = check_project(source, threads=1)
        assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == expected

        moved = '\n' + source.read_text()
        diagnostics = server.change_document(source.as_uri(), moved, 2)
        assert [(d.code, d.severity) for d in diagnostics] == expected
        if diagnostics:
            assert [d.span.start.line for d in diagnostics] == [1, 4]
            assert all(d.tags == ('unnecessary',) for d in diagnostics)

        used = moved.replace(
            '    variable version', '    variable version; puts $version $argument'
        )
        assert server.change_document(source.as_uri(), used, 3) == ()
    finally:
        server.shutdown()


@pytest.mark.parametrize('severity', ['default', 'information', 'error', 'off'])
def test_creation_hints_use_the_same_rules_in_the_editor_and_checker(
    tmp_path: Path, severity: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(f'diagnostic missing-variable {severity}\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'proc example {} {\n'
        '    incr count\n'
        '    # tcl-ls: diagnostic missing-variable off\n'
        '    lappend items value\n'
        '}\n'
    )
    expected = (
        []
        if severity == 'off'
        else [('missing-variable', 'hint' if severity == 'default' else severity)]
    )
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == expected
        report = check_project(source, threads=1)
        assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == expected

        # A cached procedure body must move its diagnostic after a leading edit.
        moved = '\n' + source.read_text()
        diagnostics = server.change_document(source.as_uri(), moved, 2)
        assert [(d.code, d.severity) for d in diagnostics] == expected
        if diagnostics:
            assert diagnostics[0].span.start.line == 2

        changed = moved.replace('    incr count', '    set count 0; incr count')
        assert server.change_document(source.as_uri(), changed, 3) == ()
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_project_diagnostic_rules_agree_in_editor_and_checker(tmp_path: Path, threads: int) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'diagnostic unresolved-command error\n'
        'diagnostic unresolved-variable off\n'
        'diagnostic wrong-argument-count information\n'
        'diagnostic unmatched-brace hint\n',
    )
    source = tmp_path / 'main.tcl'
    source.write_text('proc run {} {puts $missing}\nmissing_command\nset\nset data {\n')
    expected = [
        ('unmatched-brace', 'hint'),
        ('unresolved-command', 'error'),
        ('wrong-argument-count', 'information'),
    ]
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == expected
        report = check_project(source, threads=threads)
        assert (
            sorted((d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics)
            == expected
        )
        # Suppression does not erase the raw syntax facts used by analysis.
        assert server.documents[source.as_uri()].facts.diagnostics[0].severity == 'error'
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_value_constraint_checks_agree_in_editor_and_checker(tmp_path: Path, threads: int) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('diagnostic invalid-value hint\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        '# @type integer\nset count auto\n'
        'expr {$count + 1}\n'
        'expr {0 && (1 +)}\n'
        '# tcl-ls: diagnostic invalid-expr-operand off\n'
        'expr {"bad" + 1}\n'
        'proc mixed {flag} {\n'
        '    if {$flag} {set a {a 1 2 3}} else {set a 1}\n'
        '    expr 1 + $a\n'
        '}\n'
    )
    expected = [
        ('invalid-expr', 'error'),
        ('invalid-expr', 'warning'),
        ('invalid-expr-operand', 'error'),
        ('invalid-value', 'hint'),
    ]
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == expected
        report = check_project(source, threads=threads)
        assert (
            sorted((d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics)
            == expected
        )
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_path_rules_and_nested_configs_override_project_defaults(
    tmp_path: Path, threads: int
) -> None:
    vendor = tmp_path / 'vendor'
    nested = vendor / 'nested'
    nested.mkdir(parents=True)
    (tmp_path / 'tcllsrc.tcl').write_text(
        'diagnostic unresolved-* error\n'
        'diagnostic unresolved-command off -path vendor\n'
        'diagnostic unresolved-command information -path vendor/*.tcl\n'
        'diagnostic unresolved-command default -path **/keep.tcl\n',
    )
    (nested / 'tcllsrc.tcl').write_text(
        'diagnostic unresolved-command hint -path special.tcl\n',
    )
    expected = {
        'main.tcl': [('unresolved-command', 'error')],
        'keep.tcl': [('unresolved-command', 'warning')],
        'vendor/direct.tcl': [('unresolved-command', 'information')],
        'vendor/nested/hidden.tcl': [],
        'vendor/nested/keep.tcl': [('unresolved-command', 'warning')],
        'vendor/nested/special.tcl': [('unresolved-command', 'hint')],
    }
    server = LanguageServer()
    try:
        for relative, diagnostics in expected.items():
            path = tmp_path / relative
            path.write_text('missing_command\n')
            assert _open_diagnostics(server, path) == diagnostics
        report = check_project(tmp_path, threads=threads)
        reported: dict[str, list[tuple[str, str]]] = {}
        for item in report.diagnostics:
            name = item.path.relative_to(tmp_path).as_posix()
            reported.setdefault(name, []).append((item.diagnostic.code, item.diagnostic.severity))
        assert reported == {
            name: diagnostics for name, diagnostics in expected.items() if diagnostics
        }
    finally:
        server.shutdown()


def test_file_directives_override_config_without_losing_definitions(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('diagnostic * error\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'missing_command\n'
        '# tcl-ls: diagnostic-file * off\n'
        '# tcl-ls: diagnostic-file unmatched-brace default\n'
        'proc run {} {return ok}\n'
        'run\n'
        'set data {\n',
    )
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == [('unmatched-brace', 'error')]
        snapshot = server.analysis_snapshot()
        targets = definition(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=source.as_uri(),
            line=4,
            character=1,
        )
        assert targets and targets[0].range.start.line == 3
        report = check_project(source, threads=1)
        assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == [
            ('unmatched-brace', 'error'),
        ]
    finally:
        server.shutdown()


def test_only_real_comments_configure_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text(
        'set data {# tcl-ls: diagnostic-file * off}\n'
        'puts "# tcl-ls: diagnostic-file * off"\n'
        'missing_command\n'
        '# tcl-ls: diagnostic-file unresolved-command invalid\n',
    )
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == [
            ('invalid-diagnostic-directive', 'error'),
            ('unresolved-command', 'warning'),
        ]
    finally:
        server.shutdown()


def test_diagnostic_rules_reload_on_analysis_and_do_not_leak_between_files(tmp_path: Path) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text('missing_command\n')
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('diagnostic unresolved-command off\n')
    sibling = tmp_path / 'sibling.tcl'
    sibling.write_text('# tcl-ls: diagnostic-file unresolved-command hint\nmissing_command\n')
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == []
        assert _open_diagnostics(server, sibling) == [('unresolved-command', 'hint')]
        config.write_text('diagnostic unresolved-command error\n')
        diagnostics = server.change_document(source.as_uri(), source.read_text(), 2)
        assert [(item.code, item.severity) for item in diagnostics] == [
            ('unresolved-command', 'error')
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'rule',
    [
        'diagnostic unresolved-command',
        'diagnostic unresolved-command quiet',
        'diagnostic unresolved-command off -path',
        'diagnostic unresolved-command off -path /absolute',
        'diagnostic unresolved-command off -path ../outside',
        'diagnostic unresolved-command off -unknown path',
    ],
)
def test_invalid_diagnostic_config_is_rejected(tmp_path: Path, rule: str) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(rule + '\n')
    source = tmp_path / 'main.tcl'
    source.write_text('puts ok\n')
    with pytest.raises(RuntimeError, match=r'[Dd]iagnostic'):
        check_project(source, threads=1)


@pytest.mark.parametrize(
    ('rule', 'variable'),
    [('diagnostic $code off', 'code'), ('diagnostic unresolved-command {*}$level', 'level')],
)
def test_diagnostic_config_reports_undefined_tcl_variables(
    tmp_path: Path, rule: str, variable: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(rule + '\n')
    source = tmp_path / 'main.tcl'
    source.write_text('puts ok\n')
    with pytest.raises(RuntimeError, match=f'can\'t read "{variable}": no such variable'):
        check_project(source, threads=1)


def test_disabled_diagnostics_do_not_fail_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text('missing_command\n')
    (tmp_path / 'tcllsrc.tcl').write_text('diagnostic unresolved-command off\n')
    assert main([str(source), '--threads', '1', '--fail-on-diagnostics']) == 0
    assert 'No diagnostics found.' in capsys.readouterr().out


def test_statement_directives_cover_one_statement_and_override_file_rules(tmp_path: Path) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text(
        '# tcl-ls: diagnostic unresolved-command off\n'
        'if {1} {\n'
        '    missing_in_body\n'
        '    # tcl-ls: diagnostic unresolved-command hint\n'
        '    missing_nested_override\n'
        '}\n'
        'missing_after\n'
        '# tcl-ls: diagnostic unresolved-command off\n'
        'missing_first; missing_second\n'
        '# tcl-ls: diagnostic-file unresolved-command error\n'
    )
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
        expected = [(4, 'hint'), (6, 'error'), (8, 'error')]
        assert [(d.span.start.line, d.severity) for d in diagnostics] == expected
        report = check_project(source, threads=1)
        assert [
            (d.diagnostic.span.start.line, d.diagnostic.severity) for d in report.diagnostics
        ] == expected
    finally:
        server.shutdown()


def test_statement_directive_requires_a_statement_in_the_same_body(tmp_path: Path) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text('if {1} {\n# tcl-ls: diagnostic unresolved-command off\n}\nmissing\n')
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == [
            ('invalid-diagnostic-directive', 'error'),
            ('unresolved-command', 'warning'),
        ]
    finally:
        server.shutdown()


def test_command_directive_only_covers_the_next_command(tmp_path: Path) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text('# tcl-ls: diagnostic unresolved-* off\nfirst_missing; second_missing\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
        assert [d.message for d in diagnostics] == ['Unresolved command `second_missing`.']
        report = check_project(source, threads=1)
        assert [d.diagnostic.message for d in report.diagnostics] == [
            'Unresolved command `second_missing`.'
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'rule',
    [
        'unresolved-command off -scope',
        'unresolved-command off -scope command',
        'unresolved-command off -scope file',
        'unresolved-command off -scope line',
        'unresolved-command off -path file',
        'unresolved-command off -scope file -scope command',
        'unresolved-command off extra words',
        'statement unresolved-command off',
        'file unresolved-command off',
    ],
)
@pytest.mark.parametrize('directive', ['diagnostic', 'diagnostic-file'])
def test_invalid_comment_options_have_a_diagnostic_and_do_not_suppress(
    tmp_path: Path, rule: str, directive: str
) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text(f'# tcl-ls: {directive} {rule}\nmissing\n')
    server = LanguageServer()
    try:
        assert _open_diagnostics(server, source) == [
            ('invalid-diagnostic-directive', 'error'),
            ('unresolved-command', 'warning'),
        ]
        report = check_project(source, threads=1)
        assert sorted(d.diagnostic.code for d in report.diagnostics) == [
            'invalid-diagnostic-directive',
            'unresolved-command',
        ]
    finally:
        server.shutdown()
