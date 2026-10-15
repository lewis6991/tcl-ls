from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.completion import completion_items


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Alpha {meta command alpha_command {value}}\n'
        'meta module Beta {meta command beta_command {value}}\n'
        'module Alpha when {$::tool eq "alpha"}\n'
        'module Beta when {$::tool eq "beta"}\n'
    )
    return tmp_path


def backend(tool: str) -> str:
    other = 'beta' if tool == 'alpha' else 'alpha'
    return (
        f'if {{$::tool ne "{tool}"}} {{error "Wrong tool"}}\n'
        f'namespace eval {tool} {{\n'
        '    variable counter 0\n'
        '    proc run {} {\n'
        '        global tool\n'
        f'        {tool}_command value\n'
        f'        {other}_command value\n'
        '    }\n'
        '}\n'
    )


@pytest.mark.parametrize('order', [('alpha', 'beta'), ('beta', 'alpha')])
@pytest.mark.parametrize('threads', [1, 2])
def test_backends_keep_separate_guarded_environments(
    project: Path, order: tuple[str, str], threads: int
) -> None:
    server = LanguageServer()
    try:
        for tool in order:
            source = project / f'{tool}.tcl'
            text = backend(tool)
            source.write_text(text)
            diagnostics = server.open_document(source.as_uri(), text, 1)
            other = 'beta' if tool == 'alpha' else 'alpha'
            assert [(d.span.start.line, d.code, d.message) for d in diagnostics] == [
                (6, 'unresolved-command', f'Unresolved command `{other}_command`.')
            ]
            declaration = server.documents[source.as_uri()].facts.procedures[0]
            assert declaration.global_requirements == (('::tool', (tool,)),)
            snapshot = server.analysis_snapshot()
            items = completion_items(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=source.as_uri(),
                line=5,
                character=8,
            )
            assert f'{tool}_command' in {item.label for item in items.items}
            assert f'{other}_command' not in {item.label for item in items.items}
            signature = server.signature_help_at(
                snapshot, uri=source.as_uri(), line=5, character=len(text.splitlines()[5]) - 1
            )
            assert signature is not None
            assert signature.signatures[0].label == f'{tool}_command {{value}}'
        report = check_project(project, threads=threads)
        assert [
            (d.path.name, d.diagnostic.span.start.line, d.diagnostic.code)
            for d in report.diagnostics
        ] == [
            ('alpha.tcl', 6, 'unresolved-command'),
            ('beta.tcl', 6, 'unresolved-command'),
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'guard',
    [
        'if {$::tool ne "alpha"} {error "Wrong tool"}',
        'if {$::tool eq "alpha"} {} else {error "Wrong tool"}',
        'if {$::tool ne "alpha"} {return}',
        'if {$::tool ne "alpha"} {throw TOOL "Wrong tool"}',
        'set ::tool alpha\nif {$::tool ne "alpha"} {error "Wrong tool"}',
        'if {$::tool ne "alpha" || $::mode ne "batch"} {error "Wrong environment"}',
    ],
)
def test_only_the_continuing_path_establishes_a_procedure_requirement(
    project: Path, guard: str
) -> None:
    source = project / 'guard.tcl'
    source.write_text(f'{guard}\nproc run {{}} {{alpha_command value}}\n')
    assert check_project(source, threads=1).diagnostics == ()


@pytest.mark.parametrize(
    'guard',
    [
        'if {$::tool ne "alpha"} {puts "Wrong tool"}',
        'catch {if {$::tool ne "alpha"} {error "Wrong tool"}}',
        'if {$::tool ne "alpha"} {catch {error "Wrong tool"}}',
        'try {if {$::tool ne "alpha"} {error "Wrong tool"}} on error {} {}',
        'set ::tool alpha',
    ],
)
def test_checks_without_an_escaping_failure_do_not_establish_requirements(
    project: Path, guard: str
) -> None:
    source = project / 'guard.tcl'
    source.write_text(f'{guard}\nproc run {{}} {{alpha_command value}}\n')
    assert [
        (d.diagnostic.code, d.diagnostic.message)
        for d in check_project(source, threads=1).diagnostics
    ] == [('unresolved-command', 'Unresolved command `alpha_command`.')]


@pytest.mark.parametrize(
    'write',
    [
        'set ::tool beta',
        'global tool; set tool beta',
        'variable ::tool beta',
        'unset ::tool',
        'eval {set ::tool beta}',
        'source unknown.tcl',
    ],
)
def test_writes_and_unknown_execution_invalidate_guarded_tool_values(
    project: Path, write: str
) -> None:
    source = project / 'guard.tcl'
    source.write_text(
        'if {$::tool ne "alpha"} {error "Wrong tool"}\n'
        f'proc run {{}} {{\nalpha_command value\n{write}\nalpha_command value\n}}\n'
    )
    assert [
        (d.diagnostic.span.start.line, d.diagnostic.code)
        for d in check_project(source, threads=1).diagnostics
    ] == [(4, 'unresolved-command')]


def test_calls_check_guarded_procedure_requirements_across_files(project: Path) -> None:
    definition = project / 'backend.tcl'
    definition.write_text(
        'if {$::tool ne "alpha"} {error "Wrong tool"}\nproc run {} {alpha_command value}\n'
    )
    source = project / 'main.tcl'
    text = (
        'source [file join [file dirname [info script]] backend.tcl]\n'
        'set ::tool alpha\nrun\n'
        'set ::tool beta\nrun\n'
        'unset ::tool\nrun\n'
    )
    source.write_text(text)
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), text, 1)
        assert [(d.span.start.line, d.code, d.message) for d in diagnostics] == [
            (
                4,
                'incompatible-environment',
                'Call to `::run` requires `::tool` to be "alpha"; current value is "beta".',
            )
        ]
        assert server.documents[definition.as_uri()].analysis.diagnostics == ()
        report = check_project(source, threads=1)
        assert [
            (d.path, d.diagnostic.span.start.line, d.diagnostic.code) for d in report.diagnostics
        ] == [(source, 4, 'incompatible-environment')]
    finally:
        server.shutdown()


def test_changing_a_guard_refreshes_unchanged_procedure_bodies(project: Path) -> None:
    source = project / 'edit.tcl'
    text = (
        'if {$::tool ne "alpha"} {error "Wrong tool"}\n'
        'proc run {} {alpha_command value; beta_command value}\n'
    )
    source.write_text(text)
    server = LanguageServer()
    try:
        assert [d.message for d in server.open_document(source.as_uri(), text, 1)] == [
            'Unresolved command `beta_command`.'
        ]
        edited = text.replace('ne "alpha"', 'ne "beta"')
        assert [d.message for d in server.change_document(source.as_uri(), edited, 2)] == [
            'Unresolved command `alpha_command`.'
        ]
        assert server.documents[source.as_uri()].facts.procedures[0].global_requirements == (
            ('::tool', ('beta',)),
        )
    finally:
        server.shutdown()


def test_rc_dependencies_are_available_to_both_backend_environments(project: Path) -> None:
    common = project / 'common.tcl'
    common.write_text('proc shared {} {}\n')
    config = project / 'tcllsrc.tcl'
    with config.open('a') as stream:
        stream.write('meta source [file join [pwd] common.tcl]\n')
    server = LanguageServer()
    try:
        for tool in ('alpha', 'beta'):
            source = project / f'{tool}.tcl'
            text = (
                f'if {{$::tool ne "{tool}"}} {{error "Wrong tool"}}\n'
                f'proc {tool}_run {{}} {{shared; {tool}_command value}}\n'
            )
            source.write_text(text)
            assert server.open_document(source.as_uri(), text, 1) == ()
        assert common.as_uri() in server.documents
        assert check_project(project, threads=1).diagnostics == ()
    finally:
        server.shutdown()


def test_call_argument_substitutions_update_the_calling_environment(project: Path) -> None:
    source = project / 'main.tcl'
    source.write_text(
        'if {$::tool ne "alpha"} {error "Wrong tool"}\n'
        'proc run {value} {alpha_command $value}\n'
        'run [set ::tool beta]\n'
    )
    diagnostics = check_project(source, threads=1).diagnostics
    assert [(d.diagnostic.span.start.line, d.diagnostic.code) for d in diagnostics] == [
        (2, 'incompatible-environment')
    ]


def test_local_conditions_do_not_become_namespace_requirements(project: Path) -> None:
    source = project / 'main.tcl'
    source.write_text(
        'proc define {tool} {\n'
        '    if {$tool ne "alpha"} {error "Wrong tool"}\n'
        '    proc run {} {alpha_command value}\n'
        '}\n'
    )
    diagnostics = check_project(source, threads=1).diagnostics
    assert [(d.diagnostic.code, d.diagnostic.message) for d in diagnostics] == [
        ('unresolved-command', 'Unresolved command `alpha_command`.')
    ]
