from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from lsprotocol import types

from tcl_lsp.analysis import DocumentFacts, FactExtractor
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.parser import ParseResult
from tests.lsp.helpers import MAIN_URI, open_server_document


def buffer(server: LanguageServer, uri: str, text: str, version: int) -> None:
    server.workspace.put_text_document(
        types.TextDocumentItem(uri=uri, language_id='tcl', version=version, text=text)
    )


def test_completion_tokens_and_diagnostics_share_pending_analysis(
    server: LanguageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_server_document(server, 'proc original {} {}\n')
    original = server.documents[MAIN_URI]
    text = 'proc greeting {} {puts hello}\ngre\n'
    buffer(server, MAIN_URI, text, 2)
    extracts = 0
    extract = FactExtractor.extract

    def count(self: FactExtractor, parsed: ParseResult, **kwargs: Any) -> DocumentFacts:
        nonlocal extracts
        if parsed.source_id == MAIN_URI:
            extracts += 1
        return extract(self, parsed, **kwargs)

    monkeypatch.setattr(FactExtractor, 'extract', count)
    completion = server.completion_items_at(
        server.analysis_snapshot(), uri=MAIN_URI, line=1, character=3
    )
    assert [item.label for item in completion.items] == ['greeting']
    assert extracts == 1
    assert server.documents[MAIN_URI] is original
    pending = server.current_managed_document(MAIN_URI)
    assert pending is not None and pending.version == 2
    assert server.semantic_tokens(MAIN_URI) is not None
    diagnostics = server.change_document(MAIN_URI, text, 2)
    assert [d.message for d in diagnostics] == ['Unresolved command `gre`.']
    assert server.documents[MAIN_URI].syntax is pending.syntax
    assert server.semantic_tokens(MAIN_URI) is not None
    assert extracts == 1

    buffer(server, MAIN_URI, text.replace('gre\n', 'greeting\n'), 3)
    latest = server.current_managed_document(MAIN_URI)
    assert latest is not None and latest.syntax is not pending.syntax
    assert extracts == 2


@pytest.mark.parametrize('changed', ['metadata', 'configuration', 'dependency'])
def test_pending_analysis_is_invalidated_when_project_inputs_change(
    server: LanguageServer, tmp_path: Path, changed: str
) -> None:
    metadata = tmp_path / 'commands.meta.tcl'
    metadata.write_text('meta module Tcl {meta command hello {}}\n')
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text('source commands.meta.tcl\ndiagnostic unresolved-command warning\n')
    dependency = tmp_path / 'support.tcl'
    dependency.write_text('proc support {} {}\n')
    uri = (tmp_path / 'main.tcl').as_uri()
    initial = 'source [file join [file dirname [info script]] support.tcl]\n'
    open_server_document(server, initial, uri=uri)
    text = initial + 'hello\nsupport\nmissing\n'
    buffer(server, uri, text, 2)
    result = server.completion_items_at(server.analysis_snapshot(), uri=uri, line=1, character=3)
    assert [item.label for item in result.items] == ['hello']

    if changed == 'metadata':
        metadata.write_text('meta module Tcl {meta command replacement {}}\n')
        expected = [('Unresolved command `hello`.', 'warning')]
    elif changed == 'dependency':
        dependency.write_text('proc replaced {} {}\n')
        expected = [('Unresolved command `support`.', 'warning')]
    else:
        config.write_text('source commands.meta.tcl\ndiagnostic unresolved-command error\n')
        expected = []
    expected.append(
        ('Unresolved command `missing`.', 'error' if changed == 'configuration' else 'warning')
    )
    diagnostics = server.change_document(uri, text, 2)
    assert [(d.message, d.severity) for d in diagnostics] == expected


def test_pending_analysis_notices_a_previously_missing_source(
    server: LanguageServer, tmp_path: Path
) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = 'source [file join [file dirname [info script]] later.tcl]\n'
    open_server_document(server, text, uri=uri)
    text += 'later\n'
    buffer(server, uri, text, 2)
    assert not server.completion_items_at(
        server.analysis_snapshot(), uri=uri, line=1, character=5
    ).items
    (tmp_path / 'later.tcl').write_text('proc later {} {}\n')
    assert server.change_document(uri, text, 2) == ()


def test_cancelled_preparation_does_not_replace_newer_text(
    server: LanguageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_server_document(server, 'puts initial\n')
    original = server.documents[MAIN_URI]
    started = threading.Event()
    release = threading.Event()
    published = threading.Event()
    messages: list[types.PublishDiagnosticsParams] = []
    extract = FactExtractor.extract

    def block(self: FactExtractor, parsed: ParseResult, **kwargs: Any) -> DocumentFacts:
        if parsed.source_id == MAIN_URI:
            started.set()
            assert release.wait(timeout=5)
        return extract(self, parsed, **kwargs)

    def publish(params: types.PublishDiagnosticsParams) -> None:
        messages.append(params)
        published.set()

    monkeypatch.setattr(FactExtractor, 'extract', block)
    monkeypatch.setattr(server, 'text_document_publish_diagnostics', publish)
    buffer(server, MAIN_URI, 'missing_old\n', 2)
    server.schedule_document_change(MAIN_URI, 2)
    try:
        assert started.wait(timeout=5)
        buffer(server, MAIN_URI, 'puts latest\n', 3)
        server.schedule_document_change(MAIN_URI, 3)
        assert server.documents[MAIN_URI] is original
    finally:
        release.set()
    assert published.wait(timeout=5)
    assert len(messages) == 1 and messages[0].diagnostics == []
    assert server.documents[MAIN_URI].version == 3
