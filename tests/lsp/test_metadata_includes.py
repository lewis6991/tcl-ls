from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.hover import hover
from tcl_lsp.lsp.features.navigation import definition
from tcl_lsp.parser import Parser, ParseResult


def test_metadata_include_hover_describes_static_includes(tmp_path: Path) -> None:
    fragment = tmp_path / 'common.meta.tcl'
    fragment.write_text('meta command available {}\n')
    metadata = tmp_path / 'tool.meta.tcl'
    metadata.write_text('source common.meta.tcl\n')
    source = tmp_path / 'main.tcl'
    source.write_text('source common.tcl\n')
    server = LanguageServer()

    try:
        assert server.open_document(metadata.as_uri(), metadata.read_text(), 1) == ()
        metadata_hover = hover(server.documents, uri=metadata.as_uri(), line=0, character=1)
        assert metadata_hover is not None
        assert '`source path`' in metadata_hover.contents
        assert 'Include static metadata declarations' in metadata_hover.contents
        assert 'Included files inherit the enclosing module' in metadata_hover.contents
        assert '-encoding' not in metadata_hover.contents

        server.open_document(source.as_uri(), source.read_text(), 1)
        source_hover = hover(server.documents, uri=source.as_uri(), line=0, character=1)
        assert source_hover is not None
        assert 'Evaluate a file or resource as a Tcl script.' in source_hover.contents
        assert 'Include static metadata declarations' not in source_hover.contents
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_includes_inherit_module_scope_and_keep_definition_locations(
    tmp_path: Path, threads: int
) -> None:
    metadata = tmp_path / '.tcl-ls'
    parts = metadata / 'parts'
    parts.mkdir(parents=True)
    fragment = parts / 'shared.meta.tcl'
    fragment.write_text(
        'meta command shared {value}\n'
        'meta module Inner {meta command inner_only {}}\n'
        'meta command restored {}\n'
    )
    (metadata / 'tools.meta.tcl').write_text(
        'meta module Outer {\n'
        '    source parts/shared.meta.tcl\n'
        '    meta command outer_only {}\n'
        '}\n'
        'meta module Second {source parts/shared.meta.tcl}\n'
        'meta module Tcl {meta command common {}}\n'
    )
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('source .tcl-ls/tools.meta.tcl\nmodule Outer when {$::tool eq "outer"}\n')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'common\n'
        'shared value\n'
        '# tcl-ls: module Outer\n'
        'shared value\nrestored\nouter_only\ninner_only\n'
        'if {1} {\n'
        '    # tcl-ls: module Inner\n'
        '    inner_only\n'
        '}\n'
    )
    server = LanguageServer()
    try:
        assert server.open_document(config.as_uri(), config.read_text(), 1) == ()
        diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
        assert [(d.span.start.line, d.code) for d in diagnostics] == [
            (1, 'unresolved-command'),
            (6, 'unresolved-command'),
        ]
        report = check_project(source, threads=threads)
        assert [(d.diagnostic.span.start.line, d.diagnostic.code) for d in report.diagnostics] == [
            (1, 'unresolved-command'),
            (6, 'unresolved-command'),
        ]
        snapshot = server.analysis_snapshot()
        locations = definition(
            snapshot.documents,
            workspace_index=snapshot.workspace_index,
            metadata_registry=snapshot.metadata_registry,
            uri=source.as_uri(),
            line=3,
            character=2,
        )
        assert len(locations) == 1
        assert locations[0].uri == fragment.as_uri()
        assert (locations[0].range.start.line, locations[0].range.start.character) == (0, 13)
        assert (
            server.open_document(
                (tmp_path / 'second.tcl').as_uri(),
                '# tcl-ls: module Second\nshared value\nrestored\n',
                1,
            )
            == ()
        )
        # The config and its included metadata can also be edited as Tcl.
        assert server.open_document(config.as_uri(), config.read_text(), 1) == ()
    finally:
        server.shutdown()


def test_inline_modules_follow_include_order_and_restore_outer_scope(tmp_path: Path) -> None:
    (tmp_path / 'base.meta.tcl').write_text('meta command choose {one}\n')
    (tmp_path / 'later.meta.tcl').write_text('meta command choose {one two}\n')
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {\n'
        '    source base.meta.tcl\n'
        '    meta module Tool {meta command private {}}\n'
        '    source later.meta.tcl\n'
        '    meta alias selection choose\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('choose a b\nselection a b\nchoose a\nprivate\n')
    report = check_project(source, threads=1)
    assert [(d.diagnostic.span.start.line, d.diagnostic.code) for d in report.diagnostics] == [
        (2, 'wrong-argument-count'),
        (3, 'unresolved-command'),
    ]


def test_directory_discovery_does_not_load_included_fragments_twice(tmp_path: Path) -> None:
    metadata = tmp_path / 'meta'
    metadata.mkdir()
    (metadata / 'fragment.meta.tcl').write_text('meta command available {}\n')
    (metadata / 'root.meta.tcl').write_text('meta module Tcl {source fragment.meta.tcl}\n')
    source = tmp_path / 'main.tcl'
    source.write_text('available\n')
    assert check_project(source, threads=1, metadata_paths=(metadata,)).diagnostics == ()
    (metadata / 'independent.meta.tcl').write_text('meta module Tcl {meta command available {}}\n')
    with pytest.raises(RuntimeError, match='Conflicting builtin metadata'):
        check_project(source, threads=1, metadata_paths=(metadata,))


def test_saved_include_changes_refresh_editor_and_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragment = tmp_path / 'commands.meta.tcl'
    fragment.write_text('meta command choose {one}\n')
    (tmp_path / 'tcllsrc.tcl').write_text('meta module Tcl {source commands.meta.tcl}\n')
    parses: list[str] = []
    parse = Parser.parse_document

    def count(self: Parser, path: str, text: str) -> ParseResult:
        if path == fragment.as_uri():
            parses.append(text)
        return parse(self, path, text)

    monkeypatch.setattr(Parser, 'parse_document', count)
    source = tmp_path / 'main.tcl'
    source.write_text('choose a b\n')
    server = LanguageServer()
    try:
        assert [d.code for d in server.open_document(source.as_uri(), source.read_text(), 1)] == [
            'wrong-argument-count'
        ]
        assert len(parses) == 1
        server.change_document(source.as_uri(), source.read_text(), 2)
        assert len(parses) == 1
        fragment.write_text('meta command choose {one two}\n')
        assert server.change_document(source.as_uri(), source.read_text(), 3) == ()
        assert check_project(source, threads=1).diagnostics == ()
        assert len(parses) == 2
    finally:
        server.shutdown()


def test_saved_file_scoped_metadata_refreshes_binding_analysis(tmp_path: Path) -> None:
    metadata = tmp_path / 'main.meta.tcl'
    metadata.write_text('meta command wrapper {name}\n')
    (tmp_path / 'other.meta.tcl').write_text('meta command wrapper {name}\n')
    (tmp_path / 'tcllsrc.tcl').write_text('source main.meta.tcl\nsource other.meta.tcl\n')
    source = tmp_path / 'main.tcl'
    source.write_text('proc wrapper {name} {}\nproc run {} {\nwrapper value\nputs $value\n}\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
        assert [(d.span.start.line, d.code) for d in diagnostics] == [(3, 'unresolved-variable')]
        metadata.write_text('meta command wrapper {name} {bind 1 set}\n')
        assert server.change_document(source.as_uri(), source.read_text(), 2) == ()
        assert check_project(source, threads=1).diagnostics == ()
        other = tmp_path / 'other.tcl'
        other.write_text(source.read_text())
        report = check_project(other, threads=1)
        assert [d.diagnostic.code for d in report.diagnostics] == ['unresolved-variable']
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'text, line',
    [
        ('meta module Tcl {\n    meta unknown\n}\n', 1),
        ('meta module Tcl {source fragment.meta.tcl}\nsource fragment.meta.tcl\n', 1),
    ],
)
def test_invalid_metadata_reports_the_declaration_or_its_include(
    tmp_path: Path, text: str, line: int
) -> None:
    (tmp_path / 'fragment.meta.tcl').write_text('meta override custom {}\n')
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(text)
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), text, 1)
        assert [(d.span.start.line, d.code) for d in diagnostics] == [
            (line, 'invalid-project-config')
        ]
        report = check_project(config, threads=1)
        assert [(d.diagnostic.span.start.line, d.diagnostic.code) for d in report.diagnostics] == [
            (line, 'invalid-project-config')
        ]
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'include', ['source b.meta.tcl', 'source missing.meta.tcl', 'source $computed']
)
def test_bad_includes_report_errors_without_executing_tcl(tmp_path: Path, include: str) -> None:
    (tmp_path / 'a.meta.tcl').write_text(include + '\n')
    (tmp_path / 'b.meta.tcl').write_text('source a.meta.tcl\n')
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('source a.meta.tcl\n')
    server = LanguageServer()
    try:
        diagnostics = server.open_document(config.as_uri(), config.read_text(), 1)
        assert len(diagnostics) == 1
        assert diagnostics[0].code == 'invalid-project-config'
        assert diagnostics[0].span.start.line == 0
    finally:
        server.shutdown()
