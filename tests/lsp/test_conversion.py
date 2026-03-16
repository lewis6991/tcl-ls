from __future__ import annotations

import pytest
from pydantic import ValidationError

from tcl_lsp.common import Diagnostic, DocumentSymbol, Location, Position, Span
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp.conversion import diagnostic_to_lsp, document_symbol_to_lsp, location_to_lsp
from tcl_lsp.lsp.model import DidOpenTextDocumentParams


def test_location_to_lsp_renames_span_and_omits_offsets() -> None:
    location = Location(
        uri='file:///main.tcl',
        span=Span(
            start=Position(offset=7, line=1, character=2),
            end=Position(offset=11, line=1, character=6),
        ),
    )

    assert location_to_lsp(location).model_dump() == {
        'uri': 'file:///main.tcl',
        'range': {
            'start': {'line': 1, 'character': 2},
            'end': {'line': 1, 'character': 6},
        },
    }


def test_diagnostic_to_lsp_maps_severity() -> None:
    diagnostic = Diagnostic(
        span=Span(
            start=Position(offset=0, line=0, character=0),
            end=Position(offset=4, line=0, character=4),
        ),
        severity='warning',
        message='Potential issue.',
        source='tcl-ls',
        code='demo-warning',
    )

    assert diagnostic_to_lsp(diagnostic).model_dump() == {
        'range': {
            'start': {'line': 0, 'character': 0},
            'end': {'line': 0, 'character': 4},
        },
        'severity': 2,
        'code': 'demo-warning',
        'source': 'tcl-ls',
        'message': 'Potential issue.',
    }


def test_document_symbol_to_lsp_renames_selection_range_and_listifies_children() -> None:
    child = DocumentSymbol(
        name='childVar',
        kind='variable',
        span=Span(
            start=Position(offset=10, line=1, character=4),
            end=Position(offset=18, line=1, character=12),
        ),
        selection_span=Span(
            start=Position(offset=10, line=1, character=4),
            end=Position(offset=18, line=1, character=12),
        ),
        children=(),
    )
    parent = DocumentSymbol(
        name='demo',
        kind='function',
        span=Span(
            start=Position(offset=0, line=0, character=0),
            end=Position(offset=20, line=2, character=1),
        ),
        selection_span=Span(
            start=Position(offset=5, line=0, character=5),
            end=Position(offset=9, line=0, character=9),
        ),
        children=(child,),
    )

    assert document_symbol_to_lsp(parent).model_dump() == {
        'name': 'demo',
        'kind': 12,
        'range': {
            'start': {'line': 0, 'character': 0},
            'end': {'line': 2, 'character': 1},
        },
        'selectionRange': {
            'start': {'line': 0, 'character': 5},
            'end': {'line': 0, 'character': 9},
        },
        'children': [
            {
                'name': 'childVar',
                'kind': 13,
                'range': {
                    'start': {'line': 1, 'character': 4},
                    'end': {'line': 1, 'character': 12},
                },
                'selectionRange': {
                    'start': {'line': 1, 'character': 4},
                    'end': {'line': 1, 'character': 12},
                },
                'children': [],
            }
        ],
    }


def test_did_open_params_accept_wire_aliases_and_reject_bool_versions() -> None:
    parsed = DidOpenTextDocumentParams.model_validate(
        {
            'textDocument': {
                'uri': 'file:///main.tcl',
                'languageId': 'tcl',
                'version': 1,
                'text': 'puts ok\n',
            }
        }
    )

    assert parsed.text_document.uri == 'file:///main.tcl'
    assert parsed.text_document.language_id == 'tcl'
    assert parsed.text_document.version == 1

    with pytest.raises(ValidationError):
        DidOpenTextDocumentParams.model_validate(
            {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': True,
                    'text': 'puts ok\n',
                }
            }
        )


def test_language_server_initialize_serializes_protocol_models(server: LanguageServer) -> None:
    responses = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'clientInfo': {'name': 'test-client'}},
        }
    )

    assert responses == [
        {
            'jsonrpc': '2.0',
            'id': 1,
            'result': {
                'capabilities': {
                    'textDocumentSync': 1,
                    'definitionProvider': True,
                    'referencesProvider': True,
                    'hoverProvider': True,
                    'documentSymbolProvider': True,
                    'semanticTokensProvider': {
                        'legend': {
                            'tokenTypes': [
                                'comment',
                                'keyword',
                                'namespace',
                                'function',
                                'parameter',
                                'variable',
                                'string',
                                'operator',
                            ],
                            'tokenModifiers': ['declaration', 'defaultLibrary'],
                        },
                        'full': True,
                    },
                }
            },
        }
    ]


def test_language_server_rejects_bool_positions(server: LanguageServer) -> None:
    responses = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 7,
            'method': 'textDocument/definition',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': True, 'character': 1},
            },
        }
    )

    assert responses == [
        {
            'jsonrpc': '2.0',
            'id': 7,
            'error': {'code': -32602, 'message': 'Invalid params.'},
        }
    ]
