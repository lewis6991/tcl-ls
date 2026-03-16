from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

type JsonObject = dict[str, object]
type JsonValue = object
type MessageId = StrictInt | str

_DIAGNOSTIC_SEVERITY_MAP = {
    'error': 1,
    'warning': 2,
    'information': 3,
    'hint': 4,
}
_DOCUMENT_SYMBOL_KIND_MAP = {
    'namespace': 3,
    'function': 12,
    'variable': 13,
}


class ProtocolModel(BaseModel):
    model_config = ConfigDict(
        extra='ignore',
        from_attributes=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class LspPosition(ProtocolModel):
    line: StrictInt
    character: StrictInt


class LspRange(ProtocolModel):
    start: LspPosition
    end: LspPosition


class LspLocation(ProtocolModel):
    uri: str
    range: LspRange = Field(validation_alias='span')


class LspDiagnostic(ProtocolModel):
    range: LspRange = Field(validation_alias='span')
    severity: StrictInt
    code: str
    source: str
    message: str

    @field_validator('severity', mode='before')
    @classmethod
    def _map_severity(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return _DIAGNOSTIC_SEVERITY_MAP[value]
        except KeyError as exc:
            raise ValueError(f'Unsupported diagnostic severity: {value!r}') from exc


class MarkupContent(ProtocolModel):
    kind: Literal['plaintext', 'markdown']
    value: str


class LspHover(ProtocolModel):
    contents: MarkupContent
    range: LspRange


class LspDocumentSymbol(ProtocolModel):
    name: str
    kind: StrictInt
    range: LspRange = Field(validation_alias='span')
    selection_range: LspRange = Field(alias='selectionRange', validation_alias='selection_span')
    children: list[LspDocumentSymbol] = Field(default_factory=list)

    @field_validator('kind', mode='before')
    @classmethod
    def _map_kind(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return _DOCUMENT_SYMBOL_KIND_MAP[value]
        except KeyError as exc:
            raise ValueError(f'Unsupported document symbol kind: {value!r}') from exc


class PublishDiagnosticsParams(ProtocolModel):
    uri: str
    diagnostics: list[LspDiagnostic]


class TextDocumentItem(ProtocolModel):
    uri: str
    language_id: str = Field(alias='languageId')
    version: StrictInt
    text: str


class TextDocumentIdentifier(ProtocolModel):
    uri: str


class VersionedTextDocumentIdentifier(ProtocolModel):
    uri: str
    version: StrictInt


class TextDocumentContentChangeEvent(ProtocolModel):
    text: str


class DidOpenTextDocumentParams(ProtocolModel):
    text_document: TextDocumentItem = Field(alias='textDocument')


class DidChangeTextDocumentParams(ProtocolModel):
    text_document: VersionedTextDocumentIdentifier = Field(alias='textDocument')
    content_changes: list[TextDocumentContentChangeEvent] = Field(
        alias='contentChanges', min_length=1
    )


class DidCloseTextDocumentParams(ProtocolModel):
    text_document: TextDocumentIdentifier = Field(alias='textDocument')


class TextDocumentIdentifierParams(ProtocolModel):
    text_document: TextDocumentIdentifier = Field(alias='textDocument')


class TextDocumentPositionParams(ProtocolModel):
    text_document: TextDocumentIdentifier = Field(alias='textDocument')
    position: LspPosition


class ReferenceContext(ProtocolModel):
    include_declaration: bool = Field(alias='includeDeclaration')


class ReferenceParams(ProtocolModel):
    text_document: TextDocumentIdentifier = Field(alias='textDocument')
    position: LspPosition
    context: ReferenceContext


class ServerCapabilities(ProtocolModel):
    text_document_sync: StrictInt = Field(serialization_alias='textDocumentSync')
    definition_provider: bool = Field(serialization_alias='definitionProvider')
    references_provider: bool = Field(serialization_alias='referencesProvider')
    hover_provider: bool = Field(serialization_alias='hoverProvider')
    document_symbol_provider: bool = Field(serialization_alias='documentSymbolProvider')


class InitializeResult(ProtocolModel):
    capabilities: ServerCapabilities


class JsonRpcError(ProtocolModel):
    code: StrictInt
    message: str


class IncomingMessageEnvelope(ProtocolModel):
    jsonrpc: Literal['2.0']
    method: object
    params: JsonValue | None = None
    id: MessageId | None = None


class NotificationMessage(ProtocolModel):
    jsonrpc: Literal['2.0'] = '2.0'
    method: str
    params: JsonValue | None = None


class SuccessResponseMessage(ProtocolModel):
    jsonrpc: Literal['2.0'] = '2.0'
    id: MessageId
    result: JsonValue | None


class ErrorResponseMessage(ProtocolModel):
    jsonrpc: Literal['2.0'] = '2.0'
    id: MessageId | None
    error: JsonRpcError


type OutgoingMessage = NotificationMessage | SuccessResponseMessage | ErrorResponseMessage
