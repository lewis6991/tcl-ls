from __future__ import annotations

import json
from io import BytesIO
from typing import cast

from tcl_lsp.lsp import LanguageServer, LanguageService


def test_language_service_cross_document_navigation() -> None:
    service = LanguageService()
    service.open_document('file:///defs.tcl', 'proc greet {name} {puts $name}\n', 1)
    service.open_document('file:///use.tcl', 'greet World\n', 1)

    definition_locations = service.definition('file:///use.tcl', 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == 'file:///defs.tcl'
    assert definition_locations[0].span.start.line == 0
    assert definition_locations[0].span.start.character == 5

    hover = service.hover('file:///use.tcl', 0, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)'

    references = service.references('file:///defs.tcl', 0, 5)
    assert {(location.uri, location.span.start.line) for location in references} == {
        ('file:///defs.tcl', 0),
        ('file:///use.tcl', 0),
    }


def test_language_server_process_message_publishes_diagnostics() -> None:
    server = LanguageServer()

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///diag.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc greet {} {puts $name}\n',
                }
            },
        }
    )

    assert len(messages) == 1
    publish = cast(dict[str, object], messages[0])
    assert publish['method'] == 'textDocument/publishDiagnostics'
    params = _as_dict(publish['params'])
    assert params['uri'] == 'file:///diag.tcl'
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']


def test_language_server_run_stdio_round_trip() -> None:
    input_stream = BytesIO()
    output_stream = BytesIO()
    server = LanguageServer(input_stream=input_stream, output_stream=output_stream)

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc greet {name} {puts $name}\ngreet World\n',
                }
            },
        },
        {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'textDocument/definition',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 1, 'character': 1},
            },
        },
        {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown', 'params': {}},
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(_encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    server.run_stdio()

    messages = _decode_frames(output_stream.getvalue())
    initialize_response = next(message for message in messages if message.get('id') == 1)
    initialize_result = _as_dict(initialize_response['result'])
    capabilities = _as_dict(initialize_result['capabilities'])
    assert capabilities['definitionProvider'] is True

    diagnostics_notification = next(
        message
        for message in messages
        if message.get('method') == 'textDocument/publishDiagnostics'
    )
    diagnostics_params = _as_dict(diagnostics_notification['params'])
    assert diagnostics_params['diagnostics'] == []

    definition_response = next(message for message in messages if message.get('id') == 2)
    definition_results = cast(list[dict[str, object]], definition_response['result'])
    definition_range = _as_dict(definition_results[0]['range'])
    assert definition_results[0]['uri'] == 'file:///main.tcl'
    assert definition_range['start'] == {'line': 0, 'character': 5}

    shutdown_response = next(message for message in messages if message.get('id') == 3)
    assert shutdown_response['result'] is None


def _encode_frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
    header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
    return header + payload


def _decode_frames(payload: bytes) -> list[dict[str, object]]:
    index = 0
    messages: list[dict[str, object]] = []

    while index < len(payload):
        header_end = payload.index(b'\r\n\r\n', index)
        header_block = payload[index:header_end].decode('ascii')
        index = header_end + 4

        content_length = 0
        for header_line in header_block.split('\r\n'):
            if header_line.lower().startswith('content-length:'):
                content_length = int(header_line.split(':', maxsplit=1)[1].strip())
                break

        message_bytes = payload[index : index + content_length]
        index += content_length
        messages.append(_as_dict(json.loads(message_bytes.decode('utf-8'))))

    return messages


def _as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
