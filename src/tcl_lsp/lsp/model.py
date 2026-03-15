from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

type JsonValue = object
type MessageId = int | str


class PositionDict(TypedDict):
    line: int
    character: int


class RangeDict(TypedDict):
    start: PositionDict
    end: PositionDict


class LocationDict(TypedDict):
    uri: str
    range: RangeDict


class DiagnosticDict(TypedDict):
    range: RangeDict
    severity: int
    code: str
    source: str
    message: str


class PublishDiagnosticsParams(TypedDict):
    uri: str
    diagnostics: list[DiagnosticDict]


class TextDocumentItem(TypedDict):
    uri: str
    languageId: str
    version: int
    text: str


class TextDocumentIdentifier(TypedDict):
    uri: str


class VersionedTextDocumentIdentifier(TypedDict):
    uri: str
    version: int


class TextDocumentContentChangeEvent(TypedDict):
    text: str


class DidOpenTextDocumentParams(TypedDict):
    textDocument: TextDocumentItem


class DidChangeTextDocumentParams(TypedDict):
    textDocument: VersionedTextDocumentIdentifier
    contentChanges: list[TextDocumentContentChangeEvent]


class DidCloseTextDocumentParams(TypedDict):
    textDocument: TextDocumentIdentifier


class TextDocumentPositionParams(TypedDict):
    textDocument: TextDocumentIdentifier
    position: PositionDict


class ReferenceContextDict(TypedDict):
    includeDeclaration: bool


class ReferenceParams(TypedDict):
    textDocument: TextDocumentIdentifier
    position: PositionDict
    context: ReferenceContextDict


class MarkupContentDict(TypedDict):
    kind: Literal['plaintext']
    value: str


class HoverDict(TypedDict):
    contents: MarkupContentDict
    range: RangeDict


class DocumentSymbolDict(TypedDict):
    name: str
    kind: int
    range: RangeDict
    selectionRange: RangeDict
    children: list[DocumentSymbolDict]


class ServerCapabilities(TypedDict):
    textDocumentSync: int
    definitionProvider: bool
    referencesProvider: bool
    hoverProvider: bool
    documentSymbolProvider: bool


class InitializeResult(TypedDict):
    capabilities: ServerCapabilities


class JsonRpcError(TypedDict):
    code: int
    message: str


class RequestMessage(TypedDict):
    jsonrpc: Literal['2.0']
    id: MessageId
    method: str
    params: NotRequired[JsonValue]


class NotificationMessage(TypedDict):
    jsonrpc: Literal['2.0']
    method: str
    params: NotRequired[JsonValue]


class ResponseMessage(TypedDict):
    jsonrpc: Literal['2.0']
    id: MessageId | None
    result: NotRequired[JsonValue]
    error: NotRequired[JsonRpcError]


type OutgoingMessage = NotificationMessage | ResponseMessage
