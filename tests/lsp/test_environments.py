from pathlib import Path

import pytest

from tcl_lsp.checker.service import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.completion import completion_items
from tcl_lsp.lsp.features.navigation import definition


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / 'generated.meta.tcl').write_text(
        'meta module ExampleTool -environment\n'
        'meta command prove args\n'
        'meta command tool::prove args\n'
        'meta command tcl_clock args\n'
        'meta command encoding args\n'
        'meta command tool_body {body} {enter tcl body 1}\n',
        encoding='utf-8',
    )
    (tmp_path / 'overrides.meta.tcl').write_text(
        'meta module ExampleTool -environment\n'
        'meta override clock args\n'
        'meta alias tcl_clock clock -module Tcl\n',
        encoding='utf-8',
    )
    (tmp_path / 'tcllsrc.tcl').write_text(
        'plugin-path generated.meta.tcl\n'
        'plugin-path overrides.meta.tcl\n'
        'environment ExampleTool when {$::tool eq "example"}\n',
        encoding='utf-8',
    )
    return tmp_path


@pytest.mark.parametrize('tool_first', [True, False])
def test_open_files_keep_their_own_environment(project: Path, tool_first: bool) -> None:
    plain = (project / 'plain.tcl').as_uri()
    tool = (project / 'run_tool.tcl').as_uri()
    texts = {
        plain: 'encoding nonsense\nclock nonsense\nprove\ntool_body {missing_body_command}\n',
        tool: '# tcl-ls: env ExampleTool\nprove\nclock -none\ntcl_clock seconds\ntcl_clock nonsense\n'
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
            tool, texts[tool].replace('# tcl-ls: env ExampleTool\n', ''), 2
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
def test_explicit_check_environment_applies_to_shared_sources(project: Path, threads: int) -> None:
    shared = project / 'shared.tcl'
    (project / 'helper.tcl').write_text('proc loaded_command {} {return ok}\n', encoding='utf-8')
    shared.write_text(
        'source [file join [file dirname [info script]] helper.tcl]\n'
        'loaded_command\nprove\nclock -none\ntcl_clock seconds\n',
        encoding='utf-8',
    )

    normal = check_project(shared, threads=threads)
    selected = check_project(shared, threads=threads, environment='ExampleTool')

    assert normal.diagnostics
    assert not any('loaded_command' in item.diagnostic.message for item in normal.diagnostics)
    assert selected.diagnostics == ()


def test_unknown_environment_reports_a_configuration_error(project: Path) -> None:
    source = project / 'main.tcl'
    source.write_text('puts ok\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Unknown metadata environment'):
        check_project(source, threads=1, environment='MissingTool')


def test_nested_directives_restore_the_enclosing_environment(project: Path) -> None:
    (project / 'second.meta.tcl').write_text(
        'meta module SecondTool -environment\n'
        'meta override clock {at time}\n'
        'meta command measure args\n',
        encoding='utf-8',
    )
    with (project / 'tcllsrc.tcl').open('a', encoding='utf-8') as config:
        config.write('plugin-path second.meta.tcl\n')
    text = """namespace eval run {
    # tcl-ls: env ExampleTool

    tool::prove
    clock -none
    if {1} {
        # tcl-ls: env SecondTool
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


def test_branch_rules_select_only_known_environments(project: Path) -> None:
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


def test_only_real_comments_select_environments(project: Path) -> None:
    source = project / 'comments.tcl'
    source.write_text(
        """set data {
# tcl-ls: env ExampleTool
}
prove
# tcl-ls: env MissingTool
# tcl-ls: env
puts ok
""",
        encoding='utf-8',
    )
    result = check_project(source, threads=1)
    assert [
        (item.diagnostic.span.start.line, item.diagnostic.code) for item in result.diagnostics
    ] == [
        (3, 'unresolved-command'),
        (4, 'invalid-environment'),
        (5, 'invalid-environment'),
    ]
