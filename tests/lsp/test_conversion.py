from __future__ import annotations

from typing import cast

import pytest
from lsprotocol import types
from pygls.exceptions import JsonRpcInvalidParams
from pygls.protocol.json_rpc import RPCMessage
from tests.lsp_service import LanguageService
from tests.lsp_support import process_message

from tcl_lsp.common import Position, Span, lsp_range
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp import server as lsp_server


def _fresh_server() -> LanguageServer:
    lsp_server.reset()
    return lsp_server


def test_lsp_range_omits_offsets() -> None:
    span = Span(
        start=Position(offset=7, line=1, character=2),
        end=Position(offset=11, line=1, character=6),
    )

    assert lsp_range(span) == types.Range(
        start=types.Position(line=1, character=2),
        end=types.Position(line=1, character=6),
    )


def test_document_symbols_are_protocol_models(service: LanguageService) -> None:
    service.open_document('file:///main.tcl', 'proc greet {} {}\n', 1)

    symbols = service.server.documents['file:///main.tcl'].analysis.document_symbols

    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.name == '::greet'
    assert symbol.kind == types.SymbolKind.Function
    assert symbol.range.start == types.Position(line=0, character=0)
    assert symbol.selection_range.start == types.Position(line=0, character=5)
    assert symbol.children is None


def test_language_server_initialize_serializes_protocol_models() -> None:
    server = _fresh_server()
    responses = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'capabilities': {}, 'clientInfo': {'name': 'test-client'}},
        },
    )

    assert len(responses) == 1
    response = responses[0]
    assert response['id'] == 1
    result = response['result']
    assert isinstance(result, dict)
    capabilities = cast(dict[str, object], result['capabilities'])
    assert capabilities['definitionProvider'] is True
    assert capabilities['referencesProvider'] is True
    assert capabilities['hoverProvider'] is True
    completion_provider = cast(dict[str, object], capabilities['completionProvider'])
    assert completion_provider['triggerCharacters'] == ['$', ':']
    signature_help_provider = cast(dict[str, object], capabilities['signatureHelpProvider'])
    assert signature_help_provider['triggerCharacters'] == [' ', '\t']
    assert capabilities['documentHighlightProvider'] is True
    assert capabilities['documentSymbolProvider'] is True
    assert capabilities['renameProvider'] is True
    workspace_symbol_provider = cast(dict[str, object], capabilities['workspaceSymbolProvider'])
    assert workspace_symbol_provider == {'resolveProvider': False}
    assert capabilities['textDocumentSync'] == {'openClose': True, 'change': 1, 'save': False}
    semantic_tokens = cast(dict[str, object], capabilities['semanticTokensProvider'])
    legend = cast(dict[str, object], semantic_tokens['legend'])
    assert legend['tokenTypes'] == [
        'comment',
        'keyword',
        'namespace',
        'function',
        'parameter',
        'variable',
        'string',
        'operator',
    ]
    assert legend['tokenModifiers'] == ['declaration', 'defaultLibrary']
    assert semantic_tokens['full'] == {'delta': True}
    server_info = cast(dict[str, object], result['serverInfo'])
    assert server_info == {'name': 'tcl-ls', 'version': '0.1.0'}


def test_process_message_handles_protocol_errors(
    server: LanguageServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid(data: dict[str, object]) -> None:
        del data
        raise JsonRpcInvalidParams('invalid')

    monkeypatch.setattr(server.protocol, 'structure_message', invalid)

    assert (
        process_message(
            server,
            {
                'jsonrpc': '2.0',
                'id': 7,
                'method': 'textDocument/definition',
                'params': {
                    'textDocument': {'uri': 'file:///main.tcl'},
                    'position': {'line': 0, 'character': 1},
                },
            },
        )
        == []
    )


def test_process_message_propagates_transport_failures(
    server: LanguageServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(message: RPCMessage) -> None:
        del message
        raise RuntimeError('boom')

    monkeypatch.setattr(server.protocol, 'handle_message', boom)

    with pytest.raises(RuntimeError, match='boom'):
        process_message(
            server,
            {
                'jsonrpc': '2.0',
                'id': 8,
                'method': 'initialize',
                'params': {'capabilities': {}},
            },
        )
