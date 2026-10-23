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
        'exclude .venv\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('lib-path somewhere\nmodule ExampleTool when {1}\nexclude .venv\n')
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
            (5, 'exclude'),
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
                assert 'Without `when`, activate the module' in hover.contents
                assert 'An unknown or false result does not activate the module.' in hover.contents
            locations = service.definition(config.as_uri(), line, 2)
            assert locations and locations[0].uri.endswith('/meta/tcllsrc.meta.tcl')
        snapshot = service.server.analysis_snapshot()
        signature = service.server.signature_help_at(
            snapshot, uri=config.as_uri(), line=3, character=24
        )
        assert signature is not None
        assert signature.signatures[0].label == 'module {name ? when condition ?}'
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
        assert [d.code for d in diagnostics] == ['unresolved-command'] * 3
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
    config.write_text('source $path\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), config.read_text(), 1)
        expected = [(0, 'invalid-project-config')]
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


def test_unconditional_module_applies_to_source_and_procedures(tmp_path: Path) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    metadata = 'meta module ExampleTool {meta command prove {}}\n'
    config.write_text(metadata + 'module ExampleTool\n')
    source = tmp_path / 'main.tcl'
    text = 'proc run {} {eval {}; prove}\nprove\n'
    source.write_text(text)
    server = LanguageServer()
    try:
        assert server.open_document(config.as_uri(), config.read_text(), 1) == ()
        assert server.open_document(source.as_uri(), text, 1) == ()
        assert check_project(source, threads=1).diagnostics == ()

        config.write_text(metadata)
        diagnostics = server.change_document(source.as_uri(), text + '# recheck\n', 2)
        assert [(d.code, d.message) for d in diagnostics] == [
            ('unresolved-command', 'Unresolved command `prove`.'),
            ('unresolved-command', 'Unresolved command `prove`.'),
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'selection',
    [
        'module',
        'module {}',
        'module ExampleTool when',
        'module ExampleTool unless {1}',
        'module ExampleTool when {}',
        'module ExampleTool when {1} extra',
    ],
)
def test_incomplete_or_malformed_module_rules_are_rejected(tmp_path: Path, selection: str) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    text = selection + '\n'
    config.write_text(text)
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), text, 1)
        assert [(d.code, d.message) for d in diagnostics] == [
            (
                'invalid-project-config',
                'Module rules must be `module name ?when {condition}?`.',
            )
        ]
    finally:
        server.shutdown()
