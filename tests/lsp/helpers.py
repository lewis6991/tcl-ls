from __future__ import annotations

import json
from io import BytesIO
from typing import Any, cast

from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp import server as lsp_server
from tests.lsp_support import process_message

MAIN_URI = 'file:///main.tcl'


class NonClosingBytesIO(BytesIO):
    def close(self) -> None:
        self.flush()


class CaptureWriter:
    def __init__(self, stream: BytesIO) -> None:
        self._stream = stream

    def close(self) -> None:
        self._stream.flush()

    def write(self, data: bytes) -> None:
        self._stream.write(data)
        self._stream.flush()


def fresh_server() -> LanguageServer:
    lsp_server.reset()
    return lsp_server


def override_open_document(server: LanguageServer, open_document: object) -> None:
    cast(Any, server).open_document = open_document


def override_change_document(server: LanguageServer, change_document: object) -> None:
    cast(Any, server)._change_document = change_document


def override_schedule_document_change(
    server: LanguageServer,
    schedule_document_change: object,
) -> None:
    cast(Any, server).schedule_document_change = schedule_document_change


def open_server_document(
    server: LanguageServer,
    text: str,
    *,
    uri: str = MAIN_URI,
    version: int = 1,
) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': uri,
                    'languageId': 'tcl',
                    'version': version,
                    'text': text,
                }
            },
        },
    )


def change_server_document(
    server: LanguageServer,
    text: str,
    *,
    uri: str = MAIN_URI,
    version: int = 2,
) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {
                    'uri': uri,
                    'version': version,
                },
                'contentChanges': [{'text': text}],
            },
        },
    )


def server_position_request(
    server: LanguageServer,
    *,
    method: str,
    line: int,
    character: int,
    uri: str = MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': character},
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return as_dict(response)


def server_document_request(
    server: LanguageServer,
    *,
    method: str,
    uri: str = MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': {
                'textDocument': {'uri': uri},
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return as_dict(response)


def server_semantic_token_delta_request(
    server: LanguageServer,
    *,
    previous_result_id: str,
    uri: str = MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': 'textDocument/semanticTokens/full/delta',
            'params': {
                'textDocument': {'uri': uri},
                'previousResultId': previous_result_id,
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return as_dict(response)


def server_workspace_request(
    server: LanguageServer,
    *,
    method: str,
    params: dict[str, object],
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': params,
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return as_dict(response)


def semantic_tokens_legend(server: LanguageServer) -> tuple[list[str], list[str]]:
    semantic_tokens_provider = server.server_capabilities.semantic_tokens_provider
    assert semantic_tokens_provider is not None
    legend = semantic_tokens_provider.legend
    token_types = cast(list[str], legend.token_types)
    token_modifiers = cast(list[str], legend.token_modifiers)
    return token_types, token_modifiers


def decode_semantic_tokens(
    data: list[int],
    *,
    token_types: list[str],
    token_modifiers: list[str],
) -> list[dict[str, object]]:
    line = 0
    character = 0
    decoded: list[dict[str, object]] = []
    for index in range(0, len(data), 5):
        delta_line, delta_character, length, token_type_index, modifier_bits = data[
            index : index + 5
        ]
        line += delta_line
        if delta_line:
            character = delta_character
        else:
            character += delta_character
        decoded.append(
            {
                'line': line,
                'character': character,
                'length': length,
                'type': token_types[token_type_index],
                'modifiers': [
                    modifier
                    for bit_index, modifier in enumerate(token_modifiers)
                    if modifier_bits & (1 << bit_index)
                ],
            }
        )
    return decoded


def apply_semantic_token_edits(
    data: list[int],
    edits: list[dict[str, object]],
) -> list[int]:
    updated = list(data)
    for edit in edits:
        replacement = edit.get('data')
        updated[
            cast(int, edit['start']) : cast(int, edit['start']) + cast(int, edit['deleteCount'])
        ] = [] if replacement is None else cast(list[int], replacement)
    return updated


def semantic_token(
    *,
    line: int,
    character: int,
    length: int,
    token_type: str,
    modifiers: list[str] | None = None,
) -> dict[str, object]:
    return {
        'line': line,
        'character': character,
        'length': length,
        'type': token_type,
        'modifiers': [] if modifiers is None else modifiers,
    }


def hover_markdown_value(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = MAIN_URI,
) -> str:
    hover_response = server_position_request(
        server,
        method='textDocument/hover',
        uri=uri,
        line=line,
        character=character,
    )
    hover_result = as_dict(hover_response['result'])
    hover_contents = as_dict(hover_result['contents'])
    assert hover_contents['kind'] == 'markdown'
    return cast(str, hover_contents['value'])


def completion_items(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = MAIN_URI,
) -> list[dict[str, object]]:
    completion_response = server_position_request(
        server,
        method='textDocument/completion',
        uri=uri,
        line=line,
        character=character,
    )
    result = completion_response['result']
    if isinstance(result, list):
        return cast(list[dict[str, object]], result)
    completion_list = as_dict(result)
    return cast(list[dict[str, object]], completion_list['items'])


def signature_help_result(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = MAIN_URI,
) -> dict[str, object] | None:
    signature_response = server_position_request(
        server,
        method='textDocument/signatureHelp',
        uri=uri,
        line=line,
        character=character,
    )
    result = signature_response['result']
    if result is None:
        return None
    return as_dict(result)


def encode_frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
    header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
    return header + payload


def decode_frames(payload: bytes) -> list[dict[str, object]]:
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
        messages.append(as_dict(json.loads(message_bytes.decode('utf-8'))))

    return messages


def as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
