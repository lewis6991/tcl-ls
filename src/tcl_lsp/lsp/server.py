from __future__ import annotations

import json
import sys
from typing import BinaryIO, cast

from tcl_lsp.common import Diagnostic
from tcl_lsp.lsp.conversion import (
    diagnostic_to_lsp,
    document_symbol_to_lsp,
    hover_to_lsp,
    location_to_lsp,
)
from tcl_lsp.lsp.model import (
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenTextDocumentParams,
    InitializeResult,
    JsonRpcError,
    JsonValue,
    NotificationMessage,
    OutgoingMessage,
    PositionDict,
    PublishDiagnosticsParams,
    ReferenceParams,
    ResponseMessage,
    ServerCapabilities,
    TextDocumentContentChangeEvent,
    TextDocumentIdentifier,
    TextDocumentPositionParams,
)
from tcl_lsp.lsp.service import LanguageService

_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602


class LanguageServer:
    __slots__ = (
        '_exit_requested',
        '_input_stream',
        '_output_stream',
        '_service',
        '_shutdown_requested',
    )

    def __init__(
        self,
        service: LanguageService | None = None,
        input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None,
    ) -> None:
        self._service = LanguageService() if service is None else service
        self._input_stream = sys.stdin.buffer if input_stream is None else input_stream
        self._output_stream = sys.stdout.buffer if output_stream is None else output_stream
        self._shutdown_requested = False
        self._exit_requested = False

    def run_stdio(self) -> None:
        while not self._exit_requested:
            message = self._read_message(self._input_stream)
            if message is None:
                break
            for response in self.process_message(message):
                self._write_message(self._output_stream, response)

    def process_message(self, raw_message: object) -> list[OutgoingMessage]:
        message = _as_object(raw_message)
        if message is None:
            return [
                self._error_response(
                    request_id=None, code=_INVALID_REQUEST, message='Invalid request.'
                )
            ]

        method = message.get('method')
        request_id = _message_id(message.get('id'))
        params = message.get('params')

        if not isinstance(method, str):
            if request_id is None:
                return []
            return [
                self._error_response(
                    request_id=request_id, code=_INVALID_REQUEST, message='Invalid request.'
                )
            ]

        if method == 'initialize':
            result = self._initialize_result()
            if request_id is None:
                return []
            return [self._success_response(request_id=request_id, result=result)]

        if method == 'initialized':
            return []

        if method == 'shutdown':
            self._shutdown_requested = True
            if request_id is None:
                return []
            return [self._success_response(request_id=request_id, result=None)]

        if method == 'exit':
            self._exit_requested = True
            return []

        if method == 'textDocument/didOpen':
            parsed = _parse_did_open_params(params)
            if parsed is None:
                return self._invalid_params(request_id)
            diagnostics = self._service.open_document(
                uri=parsed['textDocument']['uri'],
                text=parsed['textDocument']['text'],
                version=parsed['textDocument']['version'],
            )
            return [self._publish_diagnostics(parsed['textDocument']['uri'], diagnostics)]

        if method == 'textDocument/didChange':
            parsed = _parse_did_change_params(params)
            if parsed is None:
                return self._invalid_params(request_id)
            latest_change = parsed['contentChanges'][-1]
            diagnostics = self._service.change_document(
                uri=parsed['textDocument']['uri'],
                text=latest_change['text'],
                version=parsed['textDocument']['version'],
            )
            return [self._publish_diagnostics(parsed['textDocument']['uri'], diagnostics)]

        if method == 'textDocument/didClose':
            parsed = _parse_did_close_params(params)
            if parsed is None:
                return self._invalid_params(request_id)
            uri = parsed['textDocument']['uri']
            self._service.close_document(uri)
            return [self._publish_diagnostics(uri, ())]

        if method == 'textDocument/definition':
            parsed = _parse_text_document_position_params(params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            locations = self._service.definition(
                uri=parsed['textDocument']['uri'],
                line=parsed['position']['line'],
                character=parsed['position']['character'],
            )
            result: JsonValue | None = [location_to_lsp(location) for location in locations] or None
            return [self._success_response(request_id=request_id, result=result)]

        if method == 'textDocument/references':
            parsed = _parse_reference_params(params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            locations = self._service.references(
                uri=parsed['textDocument']['uri'],
                line=parsed['position']['line'],
                character=parsed['position']['character'],
                include_declaration=parsed['context']['includeDeclaration'],
            )
            result = [location_to_lsp(location) for location in locations]
            return [self._success_response(request_id=request_id, result=result)]

        if method == 'textDocument/hover':
            parsed = _parse_text_document_position_params(params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            hover = self._service.hover(
                uri=parsed['textDocument']['uri'],
                line=parsed['position']['line'],
                character=parsed['position']['character'],
            )
            result = hover_to_lsp(hover) if hover is not None else None
            return [self._success_response(request_id=request_id, result=result)]

        if method == 'textDocument/documentSymbol':
            parsed = _parse_text_document_identifier(params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            symbols = self._service.document_symbols(parsed['uri'])
            result = [document_symbol_to_lsp(symbol) for symbol in symbols]
            return [self._success_response(request_id=request_id, result=result)]

        if request_id is None:
            return []
        return [
            self._error_response(
                request_id=request_id, code=_METHOD_NOT_FOUND, message='Method not found.'
            )
        ]

    def _initialize_result(self) -> InitializeResult:
        capabilities: ServerCapabilities = {
            'textDocumentSync': 1,
            'definitionProvider': True,
            'referencesProvider': True,
            'hoverProvider': True,
            'documentSymbolProvider': True,
        }
        return {'capabilities': capabilities}

    def _publish_diagnostics(
        self,
        uri: str,
        diagnostics: tuple[Diagnostic, ...],
    ) -> NotificationMessage:
        params: PublishDiagnosticsParams = {
            'uri': uri,
            'diagnostics': [diagnostic_to_lsp(diagnostic) for diagnostic in diagnostics],
        }
        return {
            'jsonrpc': '2.0',
            'method': 'textDocument/publishDiagnostics',
            'params': params,
        }

    def _success_response(self, request_id: int | str, result: JsonValue | None) -> ResponseMessage:
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'result': result,
        }

    def _error_response(
        self, request_id: int | str | None, code: int, message: str
    ) -> ResponseMessage:
        error: JsonRpcError = {'code': code, 'message': message}
        return {
            'jsonrpc': '2.0',
            'id': request_id,
            'error': error,
        }

    def _invalid_params(self, request_id: int | str | None) -> list[OutgoingMessage]:
        if request_id is None:
            return []
        return [
            self._error_response(
                request_id=request_id, code=_INVALID_PARAMS, message='Invalid params.'
            )
        ]

    def _read_message(self, stream: BinaryIO) -> JsonValue | None:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                return None
            if line in {b'\r\n', b'\n'}:
                break
            decoded = line.decode('ascii').strip()
            if ':' not in decoded:
                continue
            name, value = decoded.split(':', maxsplit=1)
            headers[name.strip().lower()] = value.strip()

        length_value = headers.get('content-length')
        if length_value is None:
            return None
        content_length = int(length_value)
        payload = stream.read(content_length)
        return cast(JsonValue, json.loads(payload.decode('utf-8')))

    def _write_message(self, stream: BinaryIO, message: OutgoingMessage) -> None:
        payload = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
        stream.write(header)
        stream.write(payload)
        stream.flush()


def _as_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    items = cast(dict[object, object], value).items()
    result: dict[str, object] = {}
    for key, item in items:
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _message_id(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | str):
        return value
    return None


def _parse_did_open_params(value: object) -> DidOpenTextDocumentParams | None:
    payload = _as_object(value)
    if payload is None:
        return None
    text_document = _as_object(payload.get('textDocument'))
    if text_document is None:
        return None
    uri = text_document.get('uri')
    language_id = text_document.get('languageId')
    version = text_document.get('version')
    text = text_document.get('text')
    if (
        not isinstance(uri, str)
        or not isinstance(language_id, str)
        or not _is_int(version)
        or not isinstance(text, str)
    ):
        return None
    return cast(
        DidOpenTextDocumentParams,
        {'textDocument': {'uri': uri, 'languageId': language_id, 'version': version, 'text': text}},
    )


def _parse_did_change_params(value: object) -> DidChangeTextDocumentParams | None:
    payload = _as_object(value)
    if payload is None:
        return None
    text_document = _as_object(payload.get('textDocument'))
    changes = _as_list(payload.get('contentChanges'))
    if text_document is None or changes is None or not changes:
        return None
    uri = text_document.get('uri')
    version = text_document.get('version')
    if not isinstance(uri, str) or not _is_int(version):
        return None
    parsed_changes: list[TextDocumentContentChangeEvent] = []
    for change in changes:
        change_object = _as_object(change)
        if change_object is None:
            return None
        text = change_object.get('text')
        if not isinstance(text, str):
            return None
        parsed_changes.append({'text': text})
    return cast(
        DidChangeTextDocumentParams,
        {'textDocument': {'uri': uri, 'version': version}, 'contentChanges': parsed_changes},
    )


def _parse_did_close_params(value: object) -> DidCloseTextDocumentParams | None:
    identifier = _parse_text_document_identifier(value)
    if identifier is None:
        return None
    return cast(DidCloseTextDocumentParams, {'textDocument': identifier})


def _parse_text_document_identifier(value: object) -> TextDocumentIdentifier | None:
    payload = _as_object(value)
    if payload is None:
        return None
    text_document = _as_object(payload.get('textDocument'))
    if text_document is None:
        return None
    uri = text_document.get('uri')
    if not isinstance(uri, str):
        return None
    return {'uri': uri}


def _parse_text_document_position_params(value: object) -> TextDocumentPositionParams | None:
    payload = _as_object(value)
    if payload is None:
        return None
    identifier = _parse_text_document_identifier(payload)
    position = _parse_position(payload.get('position'))
    if identifier is None or position is None:
        return None
    return cast(TextDocumentPositionParams, {'textDocument': identifier, 'position': position})


def _parse_reference_params(value: object) -> ReferenceParams | None:
    payload = _as_object(value)
    if payload is None:
        return None
    identifier = _parse_text_document_identifier(payload)
    position = _parse_position(payload.get('position'))
    context = _as_object(payload.get('context'))
    if identifier is None or position is None or context is None:
        return None
    include_declaration = context.get('includeDeclaration')
    if not isinstance(include_declaration, bool):
        return None
    return cast(
        ReferenceParams,
        {
            'textDocument': identifier,
            'position': position,
            'context': {'includeDeclaration': include_declaration},
        },
    )


def _parse_position(value: object) -> PositionDict | None:
    payload = _as_object(value)
    if payload is None:
        return None
    line = payload.get('line')
    character = payload.get('character')
    if not _is_int(line) or not _is_int(character):
        return None
    return cast('PositionDict', {'line': line, 'character': character})


def _as_list(value: object) -> list[object] | None:
    if isinstance(value, list):
        return cast(list[object], value)
    return None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
