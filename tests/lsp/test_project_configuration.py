from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.completion import completion_items
from tests.lsp_service import LanguageService


@pytest.mark.parametrize('threads', [1, 2])
def test_config_commands_have_editor_help_and_stay_local_to_config(
    tmp_path: Path, threads: int
) -> None:
    metadata = tmp_path / '.tcl-ls'
    metadata.mkdir()
    (metadata / 'tool.meta.tcl').write_text('meta module ExampleTool {\n}\n')
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'source .tcl-ls/tool.meta.tcl\n'
        'lib-path libs\n'
        'library-path other-libs\n'
        'module ExampleTool when {$::tool eq "example"}\n'
        'diagnostic unresolved-variable hint -path vendor\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('lib-path somewhere\nmodule ExampleTool when {1}\n')
    service = LanguageService()
    try:
        assert service.open_document(config.as_uri(), config.read_text(), 1) == ()
        assert check_project(config, threads=threads).diagnostics == ()
        for line, name in [
            (0, 'source'),
            (1, 'lib-path'),
            (2, 'library-path'),
            (3, 'module'),
            (4, 'diagnostic'),
        ]:
            hover = service.hover(config.as_uri(), line, 2)
            assert hover is not None and name in hover.contents
            assert 'Syntax:' in hover.contents
            assert '**Example**' in hover.contents
            if name == 'diagnostic':
                assert '**Levels (choose one)**' in hover.contents
                assert '**Options**' in hover.contents
                for level in ('error', 'warning', 'information', 'hint', 'off', 'default'):
                    assert f'`{level}`' in hover.contents
                assert 'Default: all files in this config' in hover.contents
            if name == 'module':
                assert 'An unknown or false result does not activate the module.' in hover.contents
            locations = service.definition(config.as_uri(), line, 2)
            assert locations and locations[0].uri.endswith('/meta/tcllsrc.meta.tcl')
        snapshot = service.server.analysis_snapshot()
        signature = service.server.signature_help_at(
            snapshot, uri=config.as_uri(), line=3, character=24
        )
        assert signature is not None
        assert signature.signatures[0].label == 'module {name when condition}'
        completions = completion_items(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=config.as_uri(),
            line=1,
            character=6,
        )
        assert [item.label for item in completions.items] == ['lib-path']

        diagnostics = service.open_document(source.as_uri(), source.read_text(), 1)
        assert [d.code for d in diagnostics] == ['unresolved-command', 'unresolved-command']
        snapshot = service.server.analysis_snapshot()
        completions = completion_items(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=source.as_uri(),
            line=0,
            character=6,
        )
        assert completions.items == ()
    finally:
        service.server.shutdown()


def test_invalid_config_can_be_opened_checked_and_corrected(tmp_path: Path) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'source $path\n'
        'module Tool when {$value eq}\n'
        'diagnostic unresolved-command quiet\n'
        'unknown-setting value\n'
        'set path libs\n'
        'lib-path {*}{one two}\n'
        'meta-path .tcl-ls\n'
    )
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), config.read_text(), 1)
        expected = [(line, 'invalid-project-config') for line in range(7)]
        assert [(d.span.start.line, d.code) for d in diagnostics] == expected
        report = check_project(config, threads=1)
        assert [
            (d.diagnostic.span.start.line, d.diagnostic.code) for d in report.diagnostics
        ] == expected
        # The invalid saved file must not block analysis of an edit or completion.
        assert [d.code for d in server.change_document(config.as_uri(), 'source {', 2)] == [
            'unmatched-brace'
        ]
        assert server.change_document(config.as_uri(), 'lib-path libs\n', 3) == ()
        # Loading settings for ordinary source remains strict.
        source = tmp_path / 'main.tcl'
        source.write_text('puts ok\n')
        with pytest.raises(RuntimeError, match=r'Invalid `tcllsrc\.tcl`'):
            check_project(source, threads=1)
    finally:
        server.shutdown()


def test_config_uses_parent_diagnostic_settings(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('diagnostic invalid-project-config hint\n')
    child = tmp_path / 'child'
    child.mkdir()
    config = child / 'tcllsrc.tcl'
    config.write_text('diagnostic * off\nunknown-setting\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), config.read_text(), 1)
        assert [(d.code, d.severity) for d in diagnostics] == [('invalid-project-config', 'hint')]
    finally:
        server.shutdown()
