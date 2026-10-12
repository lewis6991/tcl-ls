from pathlib import Path

import pytest

from tcl_lsp.checker.service import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.completion import completion_items
from tcl_lsp.lsp.features.navigation import definition


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / 'generated.meta.tcl').write_text(
        (
            'meta module ExampleTool {\n'
            '    meta command prove args\n'
            '    meta command tool_write {name} {bind 1 set}\n'
            '    meta command tool_loop {var values body} {bind list 1 foreach; enter tcl body 3}\n'
            '    meta command tool::prove args\n'
            '    meta command tcl_clock args\n'
            '    meta command encoding args\n'
            '    meta command tool_body {body} {enter tcl body 1}\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    (tmp_path / 'overrides.meta.tcl').write_text(
        (
            'meta module ExampleTool {\n'
            '    meta override clock args\n'
            '    meta alias tcl_clock clock -module Tcl\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    (tmp_path / 'tcllsrc.tcl').write_text(
        'source generated.meta.tcl\n'
        'source overrides.meta.tcl\n'
        'module ExampleTool when {$::tool eq "example"}\n',
        encoding='utf-8',
    )
    return tmp_path


@pytest.mark.parametrize('tool_first', [True, False])
def test_open_files_keep_their_own_module(project: Path, tool_first: bool) -> None:
    plain = (project / 'plain.tcl').as_uri()
    tool = (project / 'run_tool.tcl').as_uri()
    texts = {
        plain: 'encoding nonsense\nclock nonsense\nprove\ntool_body {missing_body_command}\n',
        tool: '# tcl-ls: module ExampleTool\nprove\nclock -none\ntcl_clock seconds\ntcl_clock nonsense\n'
        'tool_body {missing_body_command}\nencoding nonsense\n',
    }
    server = LanguageServer()
    try:
        for uri in (tool, plain) if tool_first else (plain, tool):
            server.open_document(uri, texts[uri], 1)

        assert sorted(d.code for d in server.documents[plain].analysis.diagnostics) == [
            'unknown-subcommand',
            'unknown-subcommand',
            'unresolved-command',
            'unresolved-command',
        ]
        assert sorted((d.code, d.message) for d in server.documents[tool].analysis.diagnostics) == [
            ('unknown-subcommand', 'Unknown subcommand `nonsense` for command `encoding`.'),
            ('unknown-subcommand', 'Unknown subcommand `nonsense` for command `tcl_clock`.'),
            ('unresolved-command', 'Unresolved command `missing_body_command`.'),
        ]
        snapshot = server.analysis_snapshot()
        for uri, line, expected in [(plain, 2, False), (tool, 1, True)]:
            completions = completion_items(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=uri,
                line=line,
                character=2,
            )
            assert ('prove' in {item.label for item in completions.items}) is expected
        signature = server.signature_help_at(snapshot, uri=tool, line=3, character=12)
        assert signature is not None
        assert [info.label for info in signature.signatures] == ['tcl_clock {subcommand args}']
        for uri, line, filename in [(tool, 2, 'overrides.meta.tcl'), (plain, 1, 'tcl.meta.tcl')]:
            locations = definition(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=uri,
                line=line,
                character=2,
            )
            assert locations and all(location.uri.endswith(filename) for location in locations)

        diagnostics = server.change_document(
            tool, texts[tool].replace('# tcl-ls: module ExampleTool\n', ''), 2
        )
        assert any(d.message == 'Unresolved command `prove`.' for d in diagnostics)
        server.close_document(tool)
        assert sorted(d.code for d in server.documents[plain].analysis.diagnostics) == [
            'unknown-subcommand',
            'unknown-subcommand',
            'unresolved-command',
            'unresolved-command',
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_explicit_check_module_applies_to_shared_sources(project: Path, threads: int) -> None:
    shared = project / 'shared.tcl'
    (project / 'helper.tcl').write_text('proc loaded_command {} {return ok}\n', encoding='utf-8')
    shared.write_text(
        'source [file join [file dirname [info script]] helper.tcl]\n'
        'loaded_command\nprove\nclock -none\ntcl_clock seconds\n',
        encoding='utf-8',
    )

    normal = check_project(shared, threads=threads)
    selected = check_project(shared, threads=threads, module='ExampleTool')

    assert normal.diagnostics
    assert not any('loaded_command' in item.diagnostic.message for item in normal.diagnostics)
    assert selected.diagnostics == ()


def test_unknown_module_reports_a_configuration_error(project: Path) -> None:
    source = project / 'main.tcl'
    source.write_text('puts ok\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Unknown metadata module'):
        check_project(source, threads=1, module='MissingTool')


def test_file_scoped_metadata_does_not_replace_module_commands(project: Path) -> None:
    (project / 'helper.meta.tcl').write_text(
        'meta command clock {fileOnly}\nmeta command prove {fileOnly}\n'
    )
    with (project / 'tcllsrc.tcl').open('a') as config:
        config.write('source helper.meta.tcl\n')
    source = project / 'main.tcl'
    source.write_text('clock seconds\n# tcl-ls: module ExampleTool\nprove\n')

    assert check_project(source, threads=1).diagnostics == ()


@pytest.mark.parametrize(
    'selection',
    ['', 'package require Sample\n', '# tcl-ls: module Sample\n', 'set ::tool sample\n'],
)
def test_module_selection_controls_commands_and_embedded_languages(
    tmp_path: Path, selection: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Sample {\n'
        '    meta command sample::run {body} {enter sample body 1}\n'
        '    meta language sample {extends tcl; command action {}}\n'
        '}\n'
        'module Sample when {$::tool eq "sample"}\n'
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    text = (
        selection
        + 'namespace import ::sample::*\n'
        + '::sample::run {action}\n'
        + 'run {action}\n'
        + 'sample::run {action}\n'
    )
    server = LanguageServer()
    try:
        server.open_document(uri, text, 1)
        analysis = server.documents[uri].analysis
        active = bool(selection)
        assert [d.code for d in analysis.diagnostics] == (
            [] if active else ['unresolved-command'] * 3
        )
        assert sum(r.reference.name == 'action' for r in analysis.resolutions) == (
            3 if active else 0
        )
        snapshot = server.analysis_snapshot()
        line = len(text.splitlines()) - 1
        items = completion_items(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=uri,
            line=line,
            character=len('sample::'),
        )
        assert ('sample::run' in {item.label for item in items.items}) is active
        signature = server.signature_help_at(
            snapshot, uri=uri, line=line, character=len('sample::run ')
        )
        assert (signature is not None) is active
        for target_line, character in [(selection.count('\n'), 22), (line, 3)]:
            locations = definition(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=uri,
                line=target_line,
                character=character,
            )
            assert bool(locations) is active
    finally:
        server.shutdown()


def test_nested_directives_restore_the_enclosing_module(project: Path) -> None:
    (project / 'second.meta.tcl').write_text(
        (
            'meta module SecondTool {\n'
            '    meta override clock {at time}\n'
            '    meta command measure args\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    with (project / 'tcllsrc.tcl').open('a', encoding='utf-8') as config:
        config.write('source second.meta.tcl\n')
    text = """namespace eval run {
    # tcl-ls: module ExampleTool

    tool::prove
    clock -none
    if {1} {
        # tcl-ls: module SecondTool
        prove
        measure
        clock at noon
        clock -none
    }
    clock -none
    measure
}
clock seconds
::tool::prove
prove
"""
    uri = (project / 'scopes.tcl').as_uri()
    server = LanguageServer()
    try:
        diagnostics = server.open_document(uri, text, 1)
        assert sorted(
            (text.splitlines()[d.span.start.line].strip(), d.code) for d in diagnostics
        ) == sorted(
            [
                ('clock -none', 'wrong-argument-count'),
                ('measure', 'unresolved-command'),
                ('::tool::prove', 'unresolved-command'),
                ('prove', 'unresolved-command'),
            ]
        )
        snapshot = server.analysis_snapshot()
        for line, character, expected in [(7, 10, True), (17, 2, False)]:
            completions = completion_items(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=uri,
                line=line,
                character=character,
            )
            assert ('prove' in {item.label for item in completions.items}) is expected
    finally:
        server.shutdown()


def test_branch_rules_select_only_known_modules(project: Path) -> None:
    source = project / 'branches.tcl'
    text = """set ::tool other
proc run {} {
    if {$::tool eq "example"} {
        tool_body {prove; ::tool::prove}
        clock -none
    } else {
        prove
    }
    if {$::tool ne "example"} {
        prove
    } else {
        prove
    }
    if {$::tool eq "example" || $::tool eq "other"} {
        prove
    }
    switch -- $::tool {
        example {prove}
        other {prove}
    }
    prove
}
set ::tool example
prove
set ::tool other
prove
"""
    source.write_text(text, encoding='utf-8')
    result = check_project(source, threads=1)
    assert [
        (item.diagnostic.span.start.line, item.diagnostic.code) for item in result.diagnostics
    ] == [
        (6, 'unresolved-command'),
        (9, 'unresolved-command'),
        (14, 'unresolved-command'),
        (18, 'unresolved-command'),
        (20, 'unresolved-command'),
        (25, 'unresolved-command'),
    ]


def test_only_real_comments_select_modules(project: Path) -> None:
    source = project / 'comments.tcl'
    source.write_text(
        """set data {
# tcl-ls: module ExampleTool
}
prove
# tcl-ls: module MissingTool
# tcl-ls: module
puts ok
""",
        encoding='utf-8',
    )
    result = check_project(source, threads=1)
    assert [
        (item.diagnostic.span.start.line, item.diagnostic.code) for item in result.diagnostics
    ] == [
        (3, 'unresolved-command'),
        (4, 'invalid-module'),
        (5, 'invalid-module'),
    ]


@pytest.mark.parametrize(
    ('statement', 'selected'),
    [
        ('if {1} {set ::tool other}', False),
        ('if {0} {set ::tool other}', True),
        ('if {$choice} {set ::tool other}', False),
        ('if {$choice} {set ::tool example} else {set ::tool example}', True),
        ('switch -- $choice {one {set ::tool other} default {set ::tool example}}', False),
        ('eval {set ::tool other}', False),
        ('tool_body {set ::tool other}', False),
        ('tool_body {puts ok}', True),
        ('catch {set ::tool other}', False),
        ('try {set ::tool other} finally {set ::tool example}', True),
        ('foreach item {a b} {set ::tool other}', False),
        ('while {$condition} {set ::tool other}', False),
        ('for {set n 0} {$n < 2} {incr n} {set ::tool other}', False),
        ('set result [set ::tool other]', False),
        ('append ::tool other', False),
        ('tool_write ::tool', False),
        ('set ::tool other; if {0 && [set ::tool example]} {}', False),
        ('set $unknown other', False),
        (
            'set ::tool other; if {$choice} {set name ::tool} else {set name ::other}; '
            'set $name example',
            False,
        ),
        ('source $path', False),
        ('proc delayed {} {set ::tool other}', True),
        ('namespace eval nested {set ::tool other}', False),
        ('set ::tool other; while {$::tool eq "example"} {puts ok}', False),
        ('set ::tool other; for {} {0} {} {set ::tool example}', False),
        ('while {$choice} {puts ok}', True),
        ('catch {puts ok}', True),
    ],
)
def test_module_rules_follow_command_effects(project: Path, statement: str, selected: bool) -> None:
    uri = (project / 'effects.tcl').as_uri()
    text = f'set ::tool example\n{statement}\nprove\nclock nonsense\n'
    server = LanguageServer()
    try:
        diagnostics = server.open_document(uri, text, 1)
        assert any(d.span.start.line == 2 for d in diagnostics) is not selected
        assert any(d.span.start.line == 3 for d in diagnostics) is not selected
        snapshot = server.analysis_snapshot()
        completions = completion_items(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=uri,
            line=2,
            character=2,
        )
        assert ('prove' in {item.label for item in completions.items}) is selected
    finally:
        server.shutdown()


def test_embedded_languages_use_the_selected_module_stack(project: Path) -> None:
    (project / 'base.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command run {body} {enter sample body 1}\n'
            '    meta language sample {command base {}}\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    with (project / 'generated.meta.tcl').open('a', encoding='utf-8') as metadata:
        metadata.write(
            'meta module ExampleTool {meta language sample {extends tcl; command native {}}}\n'
        )
    (project / 'closed.meta.tcl').write_text(
        ('meta module ClosedTool {\n    meta language sample {}\n}\n'),
        encoding='utf-8',
    )
    with (project / 'tcllsrc.tcl').open('a', encoding='utf-8') as config:
        config.write('source base.meta.tcl\nsource closed.meta.tcl\n')
    text = """run {base; native; puts ok}
if {1} {
    # tcl-ls: module ExampleTool
    run {base; native; puts ok}
    if {1} {
        # tcl-ls: module ClosedTool
        run {base; native; puts ok}
    }
    run {base; native; puts ok}
}
if {1} {
    # tcl-ls: module ClosedTool
    # tcl-ls: module ExampleTool
    run {base; native; puts ok}
}
run {base; native; puts ok}
"""
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'languages.tcl').as_uri(), text, 1)
        assert [(d.span.start.line, d.message) for d in diagnostics] == [
            (0, 'Unresolved command `native`.'),
            (0, 'Unresolved command `puts`.'),
            (6, 'Unresolved command `puts`.'),
            (15, 'Unresolved command `native`.'),
            (15, 'Unresolved command `puts`.'),
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    ('initial', 'changed', 'selected'),
    [
        ('\npr\n', '# tcl-ls: module ExampleTool\npr\n', True),
        ('# tcl-ls: module ExampleTool\npr\n', '\npr\n', False),
        ('set ::tool other\npr\n', 'set ::tool example\npr\n', True),
        ('set ::tool example\npr\n', 'set ::tool other\npr\n', False),
        (
            '# tcl-ls: module ExampleTool\npr\n',
            'if {1} {\n# tcl-ls: module ExampleTool\n}\npr\n',
            False,
        ),
        ('pr\n', 'if {$::tool eq "example"} {\npr\n', True),
    ],
)
def test_live_completion_uses_current_scopes(
    server: LanguageServer, project: Path, initial: str, changed: str, selected: bool
) -> None:
    from tests.lsp.helpers import (
        change_server_document,
        open_server_document,
        override_schedule_document_change,
    )
    from tests.lsp.helpers import (
        completion_items as request_completions,
    )

    uri = (project / 'live.tcl').as_uri()
    original_schedule = server.schedule_document_change

    def skip_change(_uri: str, _version: int) -> None:
        pass

    try:
        open_server_document(server, initial, uri=uri)
        # Hold background analysis so the request must use the live buffer.
        override_schedule_document_change(server, skip_change)
        change_server_document(server, changed, uri=uri)
        items = request_completions(
            server, uri=uri, line=len(changed.splitlines()) - 1, character=2
        )
        assert ('prove' in {item['label'] for item in items}) is selected
        assert server.documents[uri].text == initial
    finally:
        override_schedule_document_change(server, original_schedule)


@pytest.mark.parametrize(
    'loop',
    [
        'foreach item {a b}',
        'lmap item {a b}',
        'tool_loop item {a b}',
        'while {$again}',
        'for {} {$again} {}',
    ],
)
def test_loop_bodies_do_not_reuse_values_written_by_an_earlier_iteration(
    project: Path, loop: str
) -> None:
    source = project / 'loop.tcl'
    source.write_text(
        f'set ::tool example\n{loop} {{\nprove\nset ::tool other\n}}\n',
        encoding='utf-8',
    )
    report = check_project(source, threads=1)
    assert any(
        item.diagnostic.message == 'Unresolved command `prove`.' for item in report.diagnostics
    )


@pytest.mark.parametrize(
    'text',
    [
        'set tool example\nprove\nset ::tool other\nprove # unresolved\n',
        'namespace eval nested {\nset ::tool example\nset tool other\n'
        'append tool value\nprove\n}\n',
        'proc run {} {\nset ::tool example\nset tool other\nappend tool value\nprove\n}\n',
        'proc run {} {\nglobal tool\nset tool example\nprove\n'
        'set ::tool other\nprove # unresolved\n}\n',
        'namespace eval nested {proc run {} {\nvariable tool\nset tool example\n'
        'if {$::nested::tool eq "example"} {set ::tool example}\nprove\n}}\n',
        'proc run {} {\nif {$choice} {global tool}\nset ::tool example\n'
        'set tool other\nprove # unresolved\n}\n',
        'proc run {} {\nupvar #0 ::tool alias\nset ::tool example\n'
        'set alias other\nprove # unresolved\n}\n',
    ],
)
def test_module_rules_resolve_variable_identity(project: Path, text: str) -> None:
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'identity.tcl').as_uri(), text, 1)
        assert [
            d.span.start.line for d in diagnostics if d.message == 'Unresolved command `prove`.'
        ] == [line for line, source in enumerate(text.splitlines()) if '# unresolved' in source]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'statement',
    [
        'try {error other} on error {::tool} {}',
        'try {error other} trap {} {::tool} {}',
        'switch -regexp -matchvar ::tool other {other {}}',
        'switch -regexp -indexvar ::tool other {other {}}',
    ],
)
@pytest.mark.parametrize('repeated', [False, True])
def test_structured_output_variables_invalidate_module_rules(
    project: Path, statement: str, repeated: bool
) -> None:
    text = (
        f'set ::tool example\nwhile {{$again}} {{\nprove\n{statement}\n}}\n'
        if repeated
        else f'set ::tool example\n{statement}\nprove\n'
    )
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'output.tcl').as_uri(), text, 1)
        assert any(d.message == 'Unresolved command `prove`.' for d in diagnostics)
    finally:
        server.shutdown()


def test_module_can_explicitly_override_an_embedded_command(project: Path) -> None:
    (project / 'base.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command run {body} {enter sample body 1}\n'
            '    meta language sample {command action {body} {enter tcl body 1}}\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    with (project / 'generated.meta.tcl').open('a', encoding='utf-8') as metadata:
        # Generated inventories must not remove the body's precise metadata.
        metadata.write('meta module ExampleTool {meta language sample {command action args}}\n')
    (project / 'second.meta.tcl').write_text(
        ('meta module SecondTool {\n    meta language sample {override action args}\n}\n'),
        encoding='utf-8',
    )
    with (project / 'tcllsrc.tcl').open('a', encoding='utf-8') as config:
        config.write('source base.meta.tcl\nsource second.meta.tcl\n')
    text = """run {action {missing}}
# tcl-ls: module ExampleTool
run {action {missing}}
if {1} {
    # tcl-ls: module SecondTool
    run {action {missing}}
}
run {action {missing}}
"""
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'override.tcl').as_uri(), text, 1)
        assert [(d.span.start.line, d.message) for d in diagnostics] == [
            (0, 'Unresolved command `missing`.'),
            (2, 'Unresolved command `missing`.'),
            (7, 'Unresolved command `missing`.'),
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'body',
    [
        'catch {global tool}',
        'try {global tool} finally {}',
        'while {$again} {global tool}',
        'set ::tool example; tool_body {global tool}',
        'eval {global tool}',
    ],
)
def test_uncertain_bodies_invalidate_variable_links(project: Path, body: str) -> None:
    text = f'proc run {{}} {{\n{body}\nset ::tool example\nset tool other\nprove\n}}\n'
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'links.tcl').as_uri(), text, 1)
        assert any(d.message == 'Unresolved command `prove`.' for d in diagnostics)
    finally:
        server.shutdown()


def test_diagnostic_directives_do_not_change_module_flow(project: Path) -> None:
    text = (
        'set ::tool example\nwhile {$again} {\n'
        '# tcl-ls: diagnostic statement unresolved-variable off\n'
        'puts $unknown\n}\nprove\n'
    )
    server = LanguageServer()
    try:
        diagnostics = server.open_document((project / 'diagnostics.tcl').as_uri(), text, 1)
        assert diagnostics == ()
    finally:
        server.shutdown()
