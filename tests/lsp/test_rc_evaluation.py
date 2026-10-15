from pathlib import Path

import pytest

from tcl_lsp.checker import check_project
from tcl_lsp.common import Position
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.features.navigation import definition
from tcl_lsp.parser import Parser, ParseResult
from tcl_lsp.project import evaluation
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.declarations import EvaluatedDeclarations
from tests.lsp_service import LanguageService
from tests.lsp_support import process_message


@pytest.mark.parametrize('threads', [1, 2])
def test_user_rc_uses_workspace_context_to_select_shared_or_local_metadata(
    tmp_path: Path, threads: int
) -> None:
    shared = tmp_path / 'shared'
    shared.mkdir()
    (shared / 'tcllsrc.tcl').write_text('meta module Tcl {meta command selected {value}}\n')
    user_config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        'set root [dict get $::tcl_lsp::context workspace-root]\n'
        'if {[file exists [file join $root shared-enabled]] && ![file exists tcllsrc.tcl]} {\n'
        f'    source {{{shared / "tcllsrc.tcl"}}}\n'
        '}\n'
        'diagnostic unresolved-command hint\n'
    )
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    for workspace in (first, second):
        (workspace / 'src').mkdir(parents=True)
        (workspace / 'shared-enabled').touch()
    (second / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command selected {}}\ndiagnostic unresolved-command error\n'
    )
    sources = (first / 'src' / 'main.tcl', second / 'src' / 'main.tcl')
    sources[0].write_text('selected value\nmissing\n')
    sources[1].write_text('selected\nmissing\n')
    server = LanguageServer()
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 0,
            'method': 'initialize',
            'params': {
                'capabilities': {},
                'workspaceFolders': [
                    {'uri': workspace.as_uri(), 'name': workspace.name}
                    for workspace in (first, second)
                ],
            },
        },
    )
    try:
        for source, severity in zip(sources, ('hint', 'error'), strict=True):
            diagnostics = server.open_document(source.as_uri(), source.read_text(), 1)
            assert [(d.code, d.severity) for d in diagnostics] == [('unresolved-command', severity)]
            report = check_project(source.parent.parent, threads=threads)
            assert [(d.diagnostic.code, d.diagnostic.severity) for d in report.diagnostics] == [
                ('unresolved-command', severity)
            ]
        # Opening the second workspace must preserve the first workspace's shape.
        diagnostics = server.change_document(sources[0].as_uri(), sources[0].read_text(), 2)
        assert [(d.code, d.severity) for d in diagnostics] == [('unresolved-command', 'hint')]
        snapshot = server.analysis_snapshot()
        for source, target in zip(
            sources, (shared / 'tcllsrc.tcl', second / 'tcllsrc.tcl'), strict=True
        ):
            locations = definition(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                uri=source.as_uri(),
                line=0,
                character=2,
            )
            assert [location.uri for location in locations] == [target.as_uri()]
    finally:
        server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_rc_runs_normal_tcl_and_keeps_registration_locations(tmp_path: Path, threads: int) -> None:
    parts = tmp_path / 'parts'
    parts.mkdir()
    fragment = parts / 'commands.tcl'
    fragment.write_text(
        'namespace eval declarations {\n'
        '    proc install {} {\n'
        '        set shape {value}\n'
        '        meta module Tcl {\n'
        '            foreach name {first second} {\n'
        '                # A generated command.\n'
        '                meta command $name $shape\n'
        '            }\n'
        '        }\n'
        '    }\n'
        '    install\n'
        '}\n'
    )
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'set directory [file dirname [info script]]\n'
        'source [file join $directory parts commands.tcl]\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('first value\nsecond value\n')
    service = LanguageService()
    try:
        assert service.open_document(source.as_uri(), source.read_text(), 1) == ()
        assert check_project(source, threads=threads).diagnostics == ()
        for row in (0, 1):
            locations = service.definition(source.as_uri(), row, 1)
            assert [(location.uri, location.range.start.line) for location in locations] == [
                (fragment.as_uri(), 6)
            ]
            hover = service.hover(source.as_uri(), row, 1)
            assert hover is not None and 'A generated command.' in hover.contents
        # The same Tcl control flow is valid in an unsaved rc buffer.
        assert service.open_document(config.as_uri(), config.read_text(), 1) == ()
    finally:
        service.server.shutdown()


def test_rc_refreshes_when_probed_files_appear_change_and_disappear(tmp_path: Path) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'set choice [file join [dict get $::tcl_lsp::context workspace-root] choice]\n'
        'set shape {}\n'
        'if {[file exists $choice]} {\n'
        '    set channel [open $choice r]\n'
        '    set shape [read $channel]\n'
        '    close $channel\n'
        '}\n'
        'meta module Tcl {meta command selected $shape}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('selected value\n')
    choice = tmp_path / 'choice'
    service = LanguageService()
    try:
        assert [d.code for d in service.open_document(source.as_uri(), source.read_text(), 1)] == [
            'wrong-argument-count'
        ]
        choice.write_text('value')
        assert service.change_document(source.as_uri(), source.read_text(), 2) == ()
        choice.write_text('first second')
        assert [
            d.code for d in service.change_document(source.as_uri(), source.read_text(), 3)
        ] == ['wrong-argument-count']
        choice.unlink()
        assert [
            d.code for d in service.change_document(source.as_uri(), source.read_text(), 4)
        ] == ['wrong-argument-count']
        assert [d.diagnostic.code for d in check_project(source, threads=1).diagnostics] == [
            'wrong-argument-count'
        ]
    finally:
        service.server.shutdown()


def test_rc_reports_runtime_errors_and_allows_an_unsaved_correction(tmp_path: Path) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('set directory parts\nerror {Missing tool configuration}\n')
    service = LanguageService()
    try:
        diagnostics = service.open_document(config.as_uri(), config.read_text(), 1)
        assert [(d.span.start.line, d.code, d.message) for d in diagnostics] == [
            (1, 'invalid-project-config', 'Missing tool configuration')
        ]
        corrected = (
            'set enabled 1\nif {$enabled} {\n    meta module Tcl {meta command available {}}\n}\n'
        )
        assert service.change_document(config.as_uri(), corrected, 2) == ()
        source = tmp_path / 'main.tcl'
        source.write_text('puts ok\n')
        with pytest.raises(RuntimeError, match='Missing tool configuration'):
            check_project(source, threads=1)
    finally:
        service.server.shutdown()


@pytest.mark.parametrize('threads', [1, 2])
def test_rc_is_shared_by_sources_and_dependencies_in_a_workspace(
    tmp_path: Path, threads: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    config = workspace / 'tcllsrc.tcl'
    config.write_text(
        'if {[info exists seen]} {error {Tcl state leaked}}\n'
        'set seen 1\n'
        'if {[dict get $::tcl_lsp::context config-path] ne [info script]} {\n'
        '    error {Wrong config path}\n'
        '}\n'
        'if {[dict get $::tcl_lsp::context workspace-root] ne [pwd]} {\n'
        '    error {Wrong working directory}\n'
        '}\n'
        'if {[dict exists $::tcl_lsp::context source-path]} {error {Per-source context leaked}}\n'
        'meta module ExampleTool {meta command selected {value}}\n'
        'module ExampleTool when {1}\n'
    )
    # Count actual Tcl rc executions, including those for background dependencies.
    evaluate = evaluation._evaluate  # pyright: ignore[reportPrivateUsage]
    executions = 0

    def count(
        path: Path, context: ConfigContext, *, buffer: ParseResult | None
    ) -> tuple[EvaluatedDeclarations, bool]:
        nonlocal executions
        executions += 1
        return evaluate(path, context, buffer=buffer)

    monkeypatch.setattr(evaluation, '_evaluate', count)
    (workspace / 'pkgIndex.tcl').write_text(
        'package ifneeded Shared 1.0 [list source [file join $dir second.tcl]]\n'
    )
    first = workspace / 'first.tcl'
    first.write_text('package require Shared\nselected value\n')
    second = workspace / 'second.tcl'
    second.write_text('package provide Shared 1.0\n')
    service = LanguageService()
    try:
        assert service.open_document(first.as_uri(), first.read_text(), 1) == ()
        assert second.as_uri() in service.server.documents
        assert service.open_document(second.as_uri(), second.read_text(), 1) == ()
        assert service.change_document(first.as_uri(), first.read_text(), 2) == ()
        assert executions == 1
        assert service.change_document(second.as_uri(), 'selected value\n', 2) == ()
        assert executions == 1
        assert check_project(workspace, threads=threads).diagnostics == ()
        assert service.open_document(config.as_uri(), config.read_text(), 1) == ()
    finally:
        service.server.shutdown()


def test_shared_declarations_reuse_syntax_across_workspace_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fragment = tmp_path / 'commands.meta.tcl'
    fragment.write_text('# Shared command.\nmeta command selected $shape\n')
    (tmp_path / 'tcllsrc.tcl').write_text(
        'set shape {value}\nmeta module Tcl {source commands.meta.tcl}\n'
    )
    parses = 0
    parse = Parser.parse_embedded_script

    def count(self: Parser, path: str, text: str, start_position: Position) -> ParseResult:
        nonlocal parses
        if path == fragment.as_uri():
            parses += 1
        return parse(self, path, text, start_position)

    monkeypatch.setattr(Parser, 'parse_embedded_script', count)
    first = tmp_path / 'first.tcl'
    second = tmp_path / 'second.tcl'
    service = LanguageService()
    try:
        assert service.open_document(first.as_uri(), 'selected value\n', 1) == ()
        assert service.open_document(second.as_uri(), 'selected value\n', 1) == ()
        assert parses == 1
        for source in (first, second):
            hover = service.hover(source.as_uri(), 0, 1)
            assert hover is not None and 'Shared command.' in hover.contents
            locations = service.definition(source.as_uri(), 0, 1)
            assert [(loc.uri, loc.range.start.line) for loc in locations] == [
                (fragment.as_uri(), 1)
            ]

        fragment.write_text('# Updated command.\nmeta command selected {left right}\n')
        assert service.change_document(first.as_uri(), 'selected left right\n', 2) == ()
        assert parses == 2
        hover = service.hover(first.as_uri(), 0, 1)
        assert hover is not None and 'Updated command.' in hover.contents
        assert [d.code for d in service.change_document(second.as_uri(), 'selected\n', 2)] == [
            'wrong-argument-count'
        ]
        assert parses == 2
    finally:
        service.server.shutdown()


def test_rc_globs_notice_new_workspace_files(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'if {[llength [glob -nocomplain *.flag]]} {\n'
        '    meta module Tcl {meta command available {}}\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text('available\n')
    service = LanguageService()
    try:
        assert [d.code for d in service.open_document(source.as_uri(), source.read_text(), 1)] == [
            'unresolved-command'
        ]
        (tmp_path / 'enabled.flag').touch()
        assert service.change_document(source.as_uri(), source.read_text(), 2) == ()
    finally:
        service.server.shutdown()


def test_rc_exit_does_not_publish_incomplete_registrations(tmp_path: Path) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('meta module Tcl {meta command partial {}}\nexit 0\n')
    service = LanguageService()
    try:
        diagnostics = service.open_document(config.as_uri(), config.read_text(), 1)
        assert len(diagnostics) == 1
        assert diagnostics[0].code == 'invalid-project-config'
        assert 'exited before evaluation completed' in diagnostics[0].message
    finally:
        service.server.shutdown()


def test_external_dependencies_reuse_the_workspace_rc_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    library = tmp_path / 'vendor'
    library.mkdir()
    (library / 'pkgIndex.tcl').write_text(
        'package ifneeded External 1.0 [list source [file join $dir external.tcl]]\n'
    )
    dependency = library / 'external.tcl'
    dependency.write_text('package provide External 1.0\nshared\n')
    config = tmp_path / 'user-config' / 'tcl-ls' / 'tcllsrc.tcl'
    config.parent.mkdir(parents=True)
    config.write_text(
        'if {[file exists workspace-marker]} {\n'
        '    meta module Tcl {meta command shared {}}\n'
        f'    lib-path {{{library}}}\n'
        '}\n'
    )
    (workspace / 'workspace-marker').touch()
    (workspace / 'tcllsrc.tcl').write_text('# Workspace settings.\n')
    source = workspace / 'main.tcl'
    source.write_text('package require External\nshared\n')
    evaluate = evaluation._evaluate  # pyright: ignore[reportPrivateUsage]
    executions: list[tuple[Path, Path]] = []

    def count(
        path: Path, context: ConfigContext, *, buffer: ParseResult | None
    ) -> tuple[EvaluatedDeclarations, bool]:
        executions.append((path, context.workspace_root))
        return evaluate(path, context, buffer=buffer)

    monkeypatch.setattr(evaluation, '_evaluate', count)
    service = LanguageService()
    try:
        assert service.open_document(source.as_uri(), source.read_text(), 1) == ()
        assert service.server.documents[dependency.as_uri()].analysis.diagnostics == ()
        assert executions == [(config, workspace), (workspace / 'tcllsrc.tcl', workspace)]
    finally:
        service.server.shutdown()
