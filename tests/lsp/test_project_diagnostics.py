from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from lsprotocol import types

from tcl_lsp.analysis import Resolver
from tcl_lsp.analysis.facts.parsing import ListItem
from tcl_lsp.common import Position
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.parser import Parser, ParseResult
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.paths import discover_tcl_sources, read_source_file
from tests.lsp_support import wait_for_project_diagnostics

lsp_server = import_module('tcl_lsp.lsp.server')


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / 'tcllsrc.tcl').write_text('')
    return tmp_path


def _unused(server: LanguageServer, path: Path) -> list[str]:
    wait_for_project_diagnostics(server)
    return [
        d.message
        for d in server.documents[path.as_uri()].analysis.diagnostics
        if d.code == 'unused-proc'
    ]


@pytest.mark.parametrize('extension', ['.tcl', '.tm', '.test'])
def test_unopened_callers_count_without_merging_namespaces(project: Path, extension: str) -> None:
    backend = project / 'backend.tcl'
    text = (
        'namespace eval app {proc _used {} {}; proc _unused {} {}}\n'
        'namespace eval other {proc _used {} {}}\n'
    )
    backend.write_text(text)
    caller = project / f'caller{extension}'
    caller.write_text(
        'source [file join [file dirname [info script]] backend.tcl]\nproc run {} {::app::_used}\n'
    )
    server = LanguageServer()
    try:
        assert server.open_document(backend.as_uri(), text, 1) == ()
        assert _unused(server, backend) == [
            'Procedure `::app::_unused` is unused.',
            'Procedure `::other::_used` is unused.',
        ]
        assert caller.as_uri() not in server.documents
    finally:
        server.shutdown()


def test_slow_project_scan_does_not_block_normal_diagnostics_or_editor_requests(
    project: Path, monkeypatch: pytest.MonkeyPatch, server: LanguageServer
) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _unused {} {}\nunknown_command\n'
    backend.write_text(text)
    entered = threading.Event()
    release = threading.Event()

    def slow_scan(path: Path, *, context: ConfigContext | None = None) -> tuple[Path, ...]:
        entered.set()
        assert release.wait(timeout=5)
        return discover_tcl_sources(path, context=context)

    monkeypatch.setattr(lsp_server, 'discover_tcl_sources', slow_scan)
    server.workspace.put_text_document(
        types.TextDocumentItem(uri=backend.as_uri(), language_id='tcl', version=1, text=text)
    )
    try:
        diagnostics = server.open_document(backend.as_uri(), text, 1)
        assert [d.code for d in diagnostics] == ['unresolved-command']
        assert entered.wait(timeout=2)
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                document = executor.submit(
                    server.current_managed_document, backend.as_uri()
                ).result(timeout=1)
                assert document is not None
                assert [d.code for d in document.analysis.diagnostics] == ['unresolved-command']
            finally:
                release.set()
        assert _unused(server, backend) == ['Procedure `::_unused` is unused.']
    finally:
        release.set()
        server.shutdown()


def test_project_scan_and_find_references_reuse_unchanged_callers(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _used {} {}\nproc _unused {} {}\n'
    backend.write_text(text)
    caller = project / 'caller.tcl'
    caller.write_text(
        'source [file join [file dirname [info script]] backend.tcl]\n_used\nafter idle {_used}\n'
    )
    parsed: list[str] = []
    analyzed: list[str] = []
    read: list[Path] = []
    callback_reads: list[str] = []
    procedure_uses = import_module('tcl_lsp.analysis.procedure_uses')
    split_list = procedure_uses.split_tcl_list
    parse = Parser.parse_document
    analyze = Resolver.analyze

    def record_parse(self: Parser, path: str, text: str) -> ParseResult:
        parsed.append(path)
        return parse(self, path, text)

    def record_analysis(self: Resolver, uri: str, *args: Any, **kwargs: Any) -> Any:
        analyzed.append(uri)
        return analyze(self, uri, *args, **kwargs)

    def record_read(path: Path) -> str:
        read.append(path)
        return read_source_file(path)

    def record_callback(
        text: str, position: Position, *, max_items: int | None = None
    ) -> list[ListItem]:
        callback_reads.append(text)
        return split_list(text, position, max_items=max_items)

    monkeypatch.setattr(Parser, 'parse_document', record_parse)
    monkeypatch.setattr(Resolver, 'analyze', record_analysis)
    monkeypatch.setattr(lsp_server, 'read_source_file', record_read)
    monkeypatch.setattr(procedure_uses, 'split_tcl_list', record_callback)
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == ['Procedure `::_unused` is unused.']
        assert parsed.count(caller.as_uri()) == 1
        assert read.count(caller) == 1
        assert caller.as_uri() not in analyzed
        assert callback_reads.count('_used') == 1
        parsed.clear()
        read.clear()

        server.change_document(backend.as_uri(), '\n' + text, 2)
        assert _unused(server, backend) == ['Procedure `::_unused` is unused.']
        assert parsed == [backend.as_uri()]
        assert read == []
        assert caller.as_uri() not in analyzed
        assert callback_reads.count('_used') == 1

        parsed.clear()
        snapshot = server.references_snapshot(backend.as_uri(), types.Position(1, 7))
        assert any(
            reference.reference.span.start.line == 1
            for reference in snapshot.documents[caller.as_uri()].analysis.resolved_references
        )
        assert parsed == []
        assert read == []
        assert callback_reads.count('_used') == 1
    finally:
        server.shutdown()


@pytest.mark.parametrize('use', ['_helper', 'after idle {_helper}'])
def test_cached_caller_names_resolve_against_changed_declarations(project: Path, use: str) -> None:
    backend = project / 'backend.tcl'
    original = 'namespace eval app {proc _original {} {}}\n'
    backend.write_text(original)
    caller = project / 'caller.tcl'
    caller.write_text(f'namespace eval app {{{use}}}\n')
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), original, 1)
        assert _unused(server, backend) == ['Procedure `::app::_original` is unused.']

        changed = 'namespace eval app {proc _helper {} {}; proc _original {} {}}\n'
        server.change_document(backend.as_uri(), changed, 2)
        assert _unused(server, backend) == ['Procedure `::app::_original` is unused.']

        moved = '\n' + changed
        server.change_document(backend.as_uri(), moved, 3)
        assert _unused(server, backend) == ['Procedure `::app::_original` is unused.']
    finally:
        server.shutdown()


def test_cached_calls_follow_imports_when_another_file_changes(project: Path) -> None:
    backend = project / 'backend.tcl'
    text = (
        'namespace eval first {namespace export *; proc _helper {} {}}\n'
        'namespace eval second {namespace export *; proc _helper {} {}}\n'
    )
    backend.write_text(text)
    imports = project / 'imports.tcl'
    imports.write_text('namespace eval app {namespace import ::first::*}\n')
    (project / 'caller.tcl').write_text('namespace eval app {_helper}\n')
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == ['Procedure `::second::_helper` is unused.']

        imports.write_text('namespace eval app {namespace import ::second::*}\n')
        server.change_document(backend.as_uri(), text, 2)
        assert _unused(server, backend) == ['Procedure `::first::_helper` is unused.']

        imports.unlink()
        server.change_document(backend.as_uri(), text, 3)
        assert _unused(server, backend) == [
            'Procedure `::first::_helper` is unused.',
            'Procedure `::second::_helper` is unused.',
        ]
    finally:
        server.shutdown()


def test_changing_a_cached_callback_updates_which_procedure_is_used(project: Path) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _first {} {}\nproc _second {} {}\n'
    backend.write_text(text)
    caller = project / 'caller.tcl'
    caller.write_text('after idle {_first}\n')
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == ['Procedure `::_second` is unused.']

        caller.write_text('after idle {_second}\n')
        server.change_document(backend.as_uri(), text, 2)
        assert _unused(server, backend) == ['Procedure `::_first` is unused.']
    finally:
        server.shutdown()


def test_project_scan_refreshes_changed_added_and_deleted_callers(project: Path) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _helper {} {}\n'
    backend.write_text(text)
    caller = project / 'caller.tcl'
    caller.write_text('puts no_call\n')
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == ['Procedure `::_helper` is unused.']
        caller.write_text('source [file join [file dirname [info script]] backend.tcl]\n_helper\n')
        server.change_document(backend.as_uri(), text, 2)
        assert _unused(server, backend) == []
        caller.unlink()
        server.change_document(backend.as_uri(), text, 3)
        assert _unused(server, backend) == ['Procedure `::_helper` is unused.']
        caller.with_suffix('.tm').write_text(
            'source [file join [file dirname [info script]] backend.tcl]\n_helper\n'
        )
        server.change_document(backend.as_uri(), text, 4)
        assert _unused(server, backend) == []
    finally:
        server.shutdown()


def test_unsaved_callers_and_close_update_the_backend_diagnostic(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _helper {} {}\n'
    backend.write_text(text)
    caller = project / 'caller.tcl'
    caller.write_text('source [file join [file dirname [info script]] backend.tcl]\n_helper\n')
    published: list[tuple[str, list[str | int | None]]] = []
    server = LanguageServer()

    def publish(params: types.PublishDiagnosticsParams) -> None:
        published.append((params.uri, [d.code for d in params.diagnostics]))

    monkeypatch.setattr(server, 'text_document_publish_diagnostics', publish)
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == []
        server.open_document(
            caller.as_uri(),
            'source [file join [file dirname [info script]] backend.tcl]\nputs no_call\n',
            1,
        )
        assert _unused(server, backend) == ['Procedure `::_helper` is unused.']
        assert (backend.as_uri(), ['unused-proc']) in published

        server.change_document(caller.as_uri(), caller.read_text(), 2)
        assert _unused(server, backend) == []
        assert published[-1] == (backend.as_uri(), [])

        server.change_document(
            caller.as_uri(),
            'source [file join [file dirname [info script]] backend.tcl]\nputs no_call\n',
            3,
        )
        assert _unused(server, backend) == ['Procedure `::_helper` is unused.']
        server.close_document(caller.as_uri())
        assert _unused(server, backend) == []
        assert published[-1] == (backend.as_uri(), [])
    finally:
        server.shutdown()


def test_an_edit_discards_a_scan_of_old_document_text(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _helper {} {}\n'
    backend.write_text(text)
    server = LanguageServer()
    entered = threading.Event()
    release = threading.Event()
    prepare = server._prepare_project_documents  # pyright: ignore[reportPrivateUsage]

    def pause_after_scan(*args: Any, **kwargs: Any) -> Any:
        result = prepare(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(server, '_prepare_project_documents', pause_after_scan)
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert entered.wait(timeout=2)
        server.change_document(backend.as_uri(), text + '_helper\n', 2)
        release.set()
        assert _unused(server, backend) == []
    finally:
        release.set()
        server.shutdown()


def test_a_cancelled_scan_keeps_files_it_has_already_parsed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = project / 'backend.tcl'
    text = 'proc _helper {} {}\n'
    backend.write_text(text)
    caller = project / 'a_caller.tcl'
    caller.write_text('_helper\n')
    slow = project / 'z_slow.tcl'
    slow.write_text('puts slow\n')
    entered = threading.Event()
    release = threading.Event()
    parsed: list[str] = []
    parse = Parser.parse_document

    def pause_parse(self: Parser, path: str, text: str) -> ParseResult:
        parsed.append(path)
        if path == slow.as_uri():
            entered.set()
            assert release.wait(timeout=5)
        return parse(self, path, text)

    monkeypatch.setattr(Parser, 'parse_document', pause_parse)
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert entered.wait(timeout=2)
        server.change_document(backend.as_uri(), '\n' + text, 2)
        release.set()
        assert _unused(server, backend) == []
        assert parsed.count(caller.as_uri()) == 1
    finally:
        release.set()
        server.shutdown()


def test_unopened_callers_use_metadata_for_embedded_scripts(project: Path) -> None:
    (project / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command with_interrupts {code} {enter tcl body 1}}\n'
    )
    backend = project / 'backend.tcl'
    text = 'proc _helper {} {}\n'
    backend.write_text(text)
    (project / 'caller.tcl').write_text('with_interrupts {puts running; _helper}\n')
    server = LanguageServer()
    try:
        server.open_document(backend.as_uri(), text, 1)
        assert _unused(server, backend) == []
        (project / 'tcllsrc.tcl').write_text(
            'meta module Tcl {meta command with_interrupts {code}}\n'
        )
        server.change_document(backend.as_uri(), text, 2)
        assert _unused(server, backend) == ['Procedure `::_helper` is unused.']

        (project / 'tcllsrc.tcl').write_text(
            'meta module Tcl {meta command with_interrupts {code} {enter tcl body 1}}\n'
        )
        server.change_document(backend.as_uri(), text, 3)
        assert _unused(server, backend) == []
    finally:
        server.shutdown()
