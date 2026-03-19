from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import BinaryIO, cast

from pydantic import BaseModel, ValidationError

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
    ErrorResponseMessage,
    IncomingMessageEnvelope,
    InitializeParams,
    InitializeResult,
    JsonObject,
    JsonRpcError,
    JsonValue,
    LogMessageParams,
    NotificationMessage,
    OutgoingMessage,
    ProgressParams,
    PublishDiagnosticsParams,
    ReferenceParams,
    RenameParams,
    RequestMessage,
    SemanticTokens,
    SemanticTokensLegend,
    SemanticTokensOptions,
    ServerCapabilities,
    ShowMessageParams,
    SuccessResponseMessage,
    TextDocumentIdentifierParams,
    TextDocumentPositionParams,
    TextEdit,
    WorkDoneProgressBeginValue,
    WorkDoneProgressCreateParams,
    WorkDoneProgressEndValue,
    WorkDoneProgressReportValue,
    WorkspaceEdit,
)
from tcl_lsp.lsp.semantic_tokens import SEMANTIC_TOKEN_MODIFIERS, SEMANTIC_TOKEN_TYPES
from tcl_lsp.lsp.service import LanguageService

_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602


class LanguageServer:
    __slots__ = (
        '_client_supports_work_done_progress',
        '_exit_requested',
        '_indexing_notification_shown',
        '_input_stream',
        '_next_progress_token',
        '_next_server_request_id',
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
        self._client_supports_work_done_progress = False
        self._indexing_notification_shown = False
        self._next_progress_token = 1
        self._next_server_request_id = 1

    def run_stdio(self) -> None:
        while not self._exit_requested:
            message = self._read_message(self._input_stream)
            if message is None:
                break
            for response in self._process_message(
                message,
                emit_json=lambda payload: self._write_message(self._output_stream, payload),
            ):
                self._write_message(self._output_stream, response)

    def process_message(self, raw_message: object) -> list[JsonObject]:
        return self._process_message(raw_message)

    def _process_message(
        self,
        raw_message: object,
        *,
        emit_json: Callable[[JsonObject], None] | None = None,
    ) -> list[JsonObject]:
        message = _validate_model(IncomingMessageEnvelope, raw_message)
        if message is None:
            return [
                self._serialize_message(
                    self._error_response(
                        request_id=None, code=_INVALID_REQUEST, message='Invalid request.'
                    )
                )
            ]

        method = message.method
        request_id = message.id
        params = message.params

        if method is None:
            return []

        if not isinstance(method, str):
            if request_id is None:
                return []
            return [
                self._serialize_message(
                    self._error_response(
                        request_id=request_id, code=_INVALID_REQUEST, message='Invalid request.'
                    )
                )
            ]

        if method == 'initialize':
            initialize_params = _validate_model(InitializeParams, params)
            self._client_supports_work_done_progress = (
                initialize_params is not None
                and initialize_params.capabilities is not None
                and initialize_params.capabilities.window is not None
                and initialize_params.capabilities.window.work_done_progress
            )
            result = self._initialize_result()
            if request_id is None:
                return []
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'initialized':
            return [self._serialize_message(self._log_message('tcl-ls started.'))]

        if method == 'shutdown':
            self._shutdown_requested = True
            if request_id is None:
                return []
            return [
                self._serialize_message(self._success_response(request_id=request_id, result=None))
            ]

        if method == 'exit':
            self._exit_requested = True
            return []

        if method == 'textDocument/didOpen':
            parsed = _validate_model(DidOpenTextDocumentParams, params)
            if parsed is None:
                return self._invalid_params(request_id)
            responses: list[JsonObject] = []

            def emit(message: OutgoingMessage) -> None:
                serialized = self._serialize_message(message)
                if emit_json is None:
                    responses.append(serialized)
                    return
                emit_json(serialized)

            progress, finish_progress = self._begin_indexing_feedback(
                parsed.text_document.uri,
                emit,
            )
            diagnostics = self._service.open_document(
                uri=parsed.text_document.uri,
                text=parsed.text_document.text,
                version=parsed.text_document.version,
                progress=progress,
            )
            emit(self._log_message(_indexing_message(parsed.text_document.uri)))
            emit(self._publish_diagnostics(parsed.text_document.uri, diagnostics))
            finish_progress()
            return responses

        if method == 'textDocument/didChange':
            parsed = _validate_model(DidChangeTextDocumentParams, params)
            if parsed is None:
                return self._invalid_params(request_id)
            latest_change = parsed.content_changes[-1]
            diagnostics = self._service.change_document(
                uri=parsed.text_document.uri,
                text=latest_change.text,
                version=parsed.text_document.version,
            )
            return [
                self._serialize_message(
                    self._publish_diagnostics(parsed.text_document.uri, diagnostics)
                )
            ]

        if method == 'textDocument/didClose':
            parsed = _validate_model(DidCloseTextDocumentParams, params)
            if parsed is None:
                return self._invalid_params(request_id)
            uri = parsed.text_document.uri
            self._service.close_document(uri)
            return [self._serialize_message(self._publish_diagnostics(uri, ()))]

        if method == 'textDocument/definition':
            parsed = _validate_model(TextDocumentPositionParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            locations = self._service.definition(
                uri=parsed.text_document.uri,
                line=parsed.position.line,
                character=parsed.position.character,
            )
            result: JsonValue | None = [location_to_lsp(location) for location in locations] or None
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'textDocument/references':
            parsed = _validate_model(ReferenceParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            locations = self._service.references(
                uri=parsed.text_document.uri,
                line=parsed.position.line,
                character=parsed.position.character,
                include_declaration=parsed.context.include_declaration,
            )
            result = [location_to_lsp(location) for location in locations]
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'textDocument/rename':
            parsed = _validate_model(RenameParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            edits = self._service.rename(
                uri=parsed.text_document.uri,
                line=parsed.position.line,
                character=parsed.position.character,
                new_name=parsed.new_name,
            )
            result = (
                WorkspaceEdit(
                    changes={
                        uri: [
                            TextEdit.model_validate(
                                {'span': edit.span, 'newText': edit.new_text}, from_attributes=True
                            )
                            for edit in uri_edits
                        ]
                        for uri, uri_edits in edits.items()
                    }
                ).model_dump()
                if edits is not None
                else None
            )
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'textDocument/hover':
            parsed = _validate_model(TextDocumentPositionParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            hover = self._service.hover(
                uri=parsed.text_document.uri,
                line=parsed.position.line,
                character=parsed.position.character,
            )
            result = hover_to_lsp(hover) if hover is not None else None
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'textDocument/documentSymbol':
            parsed = _validate_model(TextDocumentIdentifierParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            symbols = self._service.document_symbols(parsed.text_document.uri)
            result = [document_symbol_to_lsp(symbol) for symbol in symbols]
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if method == 'textDocument/semanticTokens/full':
            parsed = _validate_model(TextDocumentIdentifierParams, params)
            if parsed is None or request_id is None:
                return self._invalid_params(request_id)
            data = self._service.semantic_tokens(parsed.text_document.uri)
            result = SemanticTokens(data=list(data)).model_dump() if data is not None else None
            return [
                self._serialize_message(
                    self._success_response(request_id=request_id, result=result)
                )
            ]

        if request_id is None:
            return []
        return [
            self._serialize_message(
                self._error_response(
                    request_id=request_id, code=_METHOD_NOT_FOUND, message='Method not found.'
                )
            )
        ]

    def _initialize_result(self) -> InitializeResult:
        capabilities = ServerCapabilities(
            text_document_sync=1,
            definition_provider=True,
            references_provider=True,
            hover_provider=True,
            document_symbol_provider=True,
            rename_provider=True,
            semantic_tokens_provider=SemanticTokensOptions(
                legend=SemanticTokensLegend(
                    tokenTypes=list(SEMANTIC_TOKEN_TYPES),
                    tokenModifiers=list(SEMANTIC_TOKEN_MODIFIERS),
                ),
                full=True,
            ),
        )
        return InitializeResult(capabilities=capabilities)

    def _publish_diagnostics(
        self,
        uri: str,
        diagnostics: tuple[Diagnostic, ...],
    ) -> NotificationMessage:
        params = PublishDiagnosticsParams(
            uri=uri,
            diagnostics=[diagnostic_to_lsp(diagnostic) for diagnostic in diagnostics],
        )
        return NotificationMessage(method='textDocument/publishDiagnostics', params=params)

    def _log_message(self, message: str, *, message_type: int = 3) -> NotificationMessage:
        params = LogMessageParams(type=message_type, message=message)
        return NotificationMessage(method='window/logMessage', params=params)

    def _show_message(self, message: str, *, message_type: int = 3) -> NotificationMessage:
        params = ShowMessageParams(type=message_type, message=message)
        return NotificationMessage(method='window/showMessage', params=params)

    def _begin_indexing_feedback(
        self,
        uri: str,
        emit: Callable[[OutgoingMessage], None],
    ) -> tuple[Callable[[str, int], None] | None, Callable[[], None]]:
        if not self._take_indexing_feedback_slot():
            return None, _noop

        if not self._client_supports_work_done_progress:
            emit(self._show_message(_indexing_notification_message(uri)))
            return None, _noop

        token = self._next_work_done_progress_token()
        emit(self._create_work_done_progress(token))
        emit(
            self._progress_notification(
                token,
                WorkDoneProgressBeginValue(
                    kind='begin',
                    title='Indexing workspace',
                    message='Starting analysis',
                    percentage=0,
                ),
            )
        )

        def report_progress(message: str, percentage: int) -> None:
            emit(
                self._progress_notification(
                    token,
                    WorkDoneProgressReportValue(
                        kind='report',
                        message=message,
                        percentage=percentage,
                    ),
                )
            )

        def finish_progress() -> None:
            emit(
                self._progress_notification(
                    token,
                    WorkDoneProgressEndValue(
                        kind='end',
                        message='Indexing complete.',
                    ),
                )
            )

        return report_progress, finish_progress

    def _take_indexing_feedback_slot(self) -> bool:
        if self._indexing_notification_shown:
            return False
        self._indexing_notification_shown = True
        return True

    def _create_work_done_progress(self, token: str) -> RequestMessage:
        return RequestMessage(
            id=self._next_server_request_message_id(),
            method='window/workDoneProgress/create',
            params=WorkDoneProgressCreateParams(token=token),
        )

    def _progress_notification(
        self,
        token: str,
        value: WorkDoneProgressBeginValue | WorkDoneProgressReportValue | WorkDoneProgressEndValue,
    ) -> NotificationMessage:
        return NotificationMessage(
            method='$/progress',
            params=ProgressParams(token=token, value=value),
        )

    def _next_work_done_progress_token(self) -> str:
        token = f'tcl-ls/indexing/{self._next_progress_token}'
        self._next_progress_token += 1
        return token

    def _next_server_request_message_id(self) -> str:
        request_id = f'tcl-ls/request/{self._next_server_request_id}'
        self._next_server_request_id += 1
        return request_id

    def _success_response(
        self, request_id: int | str, result: JsonValue | None
    ) -> SuccessResponseMessage:
        return SuccessResponseMessage(id=request_id, result=result)

    def _error_response(
        self, request_id: int | str | None, code: int, message: str
    ) -> ErrorResponseMessage:
        error = JsonRpcError(code=code, message=message)
        return ErrorResponseMessage(id=request_id, error=error)

    def _invalid_params(self, request_id: int | str | None) -> list[JsonObject]:
        if request_id is None:
            return []
        return [
            self._serialize_message(
                self._error_response(
                    request_id=request_id, code=_INVALID_PARAMS, message='Invalid params.'
                )
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

    def _write_message(self, stream: BinaryIO, message: JsonObject) -> None:
        payload = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
        stream.write(header)
        stream.write(payload)
        stream.flush()

    def _serialize_message(self, message: OutgoingMessage) -> JsonObject:
        return cast(JsonObject, message.model_dump())


def _validate_model[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT | None:
    try:
        return model_type.model_validate(value)
    except ValidationError:
        return None


def _noop() -> None:
    return None


def _indexing_message(uri: str) -> str:
    return f'Indexing workspace for {uri}.'


def _indexing_notification_message(uri: str) -> str:
    del uri
    return 'Indexing workspace.'
