from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lsprotocol import types
from pygls.lsp.server import LanguageServer as PyglsLanguageServer
from pygls.protocol.language_server import LanguageServerProtocol

from tcl_lsp import __version__
from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.common import Diagnostic, lsp_range
from tcl_lsp.lsp.document_changes import DocumentChangeWorker
from tcl_lsp.lsp.features.completion import completion_items
from tcl_lsp.lsp.features.highlights import document_highlights
from tcl_lsp.lsp.features.hover import hover
from tcl_lsp.lsp.features.navigation import definition, references
from tcl_lsp.lsp.features.rename import rename
from tcl_lsp.lsp.features.signature_help import signature_help
from tcl_lsp.lsp.features.workspace_symbols import workspace_symbols
from tcl_lsp.lsp.semantic_tokens import (
    SEMANTIC_TOKEN_MODIFIERS,
    SEMANTIC_TOKEN_TYPES,
    EncodedSemanticTokenEdit,
    diff_encoded_semantic_tokens,
    encode_document_semantic_tokens,
)
from tcl_lsp.lsp.state import (
    AnalysisSnapshot,
    IndexingProgressCallback,
    ManagedDocument,
    empty_analysis,
)
from tcl_lsp.lsp.workspace_rebuild import (
    DocumentBuildSnapshot,
    WorkspaceRebuilder,
    analysis_workspace_index,
)
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataRegistry,
)
from tcl_lsp.parser import Parser
from tcl_lsp.project.config import configured_library_paths, configured_plugin_paths
from tcl_lsp.project.paths import source_id_to_path

_DIAGNOSTIC_SEVERITY_MAP = {
    'error': types.DiagnosticSeverity.Error,
    'warning': types.DiagnosticSeverity.Warning,
    'information': types.DiagnosticSeverity.Information,
    'hint': types.DiagnosticSeverity.Hint,
}
_DIAGNOSTIC_TAG_MAP = {
    'deprecated': types.DiagnosticTag.Deprecated,
    'unnecessary': types.DiagnosticTag.Unnecessary,
}
_SEMANTIC_TOKEN_CACHE_LIMIT = 8


@dataclass(frozen=True, slots=True)
class _SemanticTokenResult:
    version: int
    data: tuple[int, ...]


class LanguageServer(PyglsLanguageServer):
    documents: dict[str, ManagedDocument]
    _change_worker: DocumentChangeWorker
    _extractor: FactExtractor
    _indexing_notification_shown: bool
    _library_paths_by_uri: dict[str, tuple[Path, ...]]
    _metadata_registry: MetadataRegistry
    _next_progress_token: int
    _next_semantic_token_result_id: int
    _next_server_request_id: int
    _open_document_uris: set[str]
    _parser: Parser
    _plugin_paths_by_uri: dict[str, tuple[Path, ...]]
    _resolver: Resolver
    _scanned_package_roots: set[Path]
    _semantic_token_results_by_uri: dict[str, OrderedDict[str, _SemanticTokenResult]]
    _state_lock: threading.RLock
    _toolkit_lock: threading.RLock
    _workspace_index: WorkspaceIndex

    def __init__(
        self,
        parser: Parser | None = None,
        extractor: FactExtractor | None = None,
        workspace_index: WorkspaceIndex | None = None,
        resolver: Resolver | None = None,
        metadata_registry: MetadataRegistry | None = None,
    ) -> None:
        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            name='tcl-ls',
            version=__version__,
            text_document_sync_kind=types.TextDocumentSyncKind.Full,
            protocol_cls=_TclLanguageServerProtocol,
        )
        self._state_lock = threading.RLock()
        self._toolkit_lock = threading.RLock()
        self._indexing_notification_shown = False
        self._next_progress_token = 1
        self._next_server_request_id = 1
        self._initialize_analysis_state(
            parser=parser,
            extractor=extractor,
            workspace_index=workspace_index,
            resolver=resolver,
            metadata_registry=metadata_registry,
        )
        self._change_worker = DocumentChangeWorker(
            apply_change=self._queued_change_document,
            current_document_version=self._current_document_version,
            publish_diagnostics=self._publish_document_diagnostics,
        )
        self._change_worker.start()

    def reset(self) -> None:
        self.shutdown()

        self.process_id = None
        self._server = None
        self._stop_event = None
        self._thread_pool = None

        self._indexing_notification_shown = False
        self._next_progress_token = 1
        self._next_server_request_id = 1

        self.__dict__.pop('open_document', None)
        cast(_TclLanguageServerProtocol, self.protocol).reset_runtime_state()
        self._initialize_analysis_state()
        self._change_worker.start()

    def shutdown(self) -> None:
        self._change_worker.stop()
        with self._toolkit_lock:
            self._extractor.close()
        super().shutdown()

    def open_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> tuple[Diagnostic, ...]:
        self._change_worker.invalidate()
        self._load_documents(((uri, text, version),), progress=progress)
        document = self.analysis_snapshot().documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self._change_worker.invalidate()
        diagnostics = self._change_document(uri, text, version)
        return () if diagnostics is None else diagnostics

    def schedule_document_change(self, uri: str, version: int) -> None:
        self._change_worker.schedule(uri, version)

    def _change_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[Diagnostic, ...] | None:
        if not self._load_documents(((uri, text, version),), should_cancel=should_cancel):
            return None
        document = self.analysis_snapshot().documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def _queued_change_document(
        self,
        uri: str,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[Diagnostic, ...] | None:
        with self._state_lock:
            if uri not in self._open_document_uris:
                return ()
        text_document = self.workspace.get_text_document(uri)
        return self._change_document(
            uri,
            text_document.source,
            0 if text_document.version is None else text_document.version,
            should_cancel=should_cancel,
        )

    def close_document(self, uri: str) -> None:
        with self._state_lock:
            self._semantic_token_results_by_uri.pop(uri, None)
            if uri not in self.documents:
                return

            self._open_document_uris.discard(uri)
            self._plugin_paths_by_uri.pop(uri, None)
            self._library_paths_by_uri.pop(uri, None)

        self._change_worker.discard(uri)
        self._load_documents(())

    @property
    def metadata_registry(self) -> MetadataRegistry:
        return self._metadata_registry

    @property
    def parser(self) -> Parser:
        return self._parser

    @property
    def extractor(self) -> FactExtractor:
        return self._extractor

    @property
    def workspace_index(self) -> WorkspaceIndex:
        return self._workspace_index

    def analysis_snapshot(self) -> AnalysisSnapshot:
        with self._state_lock:
            return AnalysisSnapshot(
                documents=self.documents,
                workspace_index=self._workspace_index,
                metadata_registry=self._metadata_registry,
            )

    def _current_document_version(self, uri: str) -> int | None:
        with self._state_lock:
            document = self.documents.get(uri)
        if document is None:
            return None
        return document.version

    def current_managed_document(self, uri: str) -> ManagedDocument | None:
        snapshot = self.analysis_snapshot()
        document = snapshot.documents.get(uri)
        workspace_document = self._workspace_document_state(uri)
        if workspace_document is None:
            return document

        text, version = workspace_document
        if document is not None and document.version == version and document.text == text:
            return document

        return self._analyze_workspace_document(
            snapshot,
            uri=uri,
            text=text,
            version=version,
        )

    def semantic_tokens(self, uri: str) -> types.SemanticTokens | None:
        current_result = self._current_semantic_token_result(uri)
        if current_result is None:
            return None

        result_id, data = current_result
        return types.SemanticTokens(data=list(data), result_id=result_id)

    def semantic_token_delta(
        self,
        uri: str,
        previous_result_id: str,
    ) -> types.SemanticTokens | types.SemanticTokensDelta | None:
        current_result = self._current_semantic_token_result(uri)
        if current_result is None:
            return None

        result_id, data = current_result
        previous_data = self._semantic_token_data(uri, previous_result_id)
        if previous_data is None:
            return types.SemanticTokens(data=list(data), result_id=result_id)

        semantic_edits: tuple[EncodedSemanticTokenEdit, ...] = diff_encoded_semantic_tokens(
            previous_data=previous_data,
            current_data=data,
        )
        edits = tuple(
            types.SemanticTokensEdit(
                start=edit.start,
                delete_count=edit.delete_count,
                data=None if edit.data is None else list(edit.data),
            )
            for edit in semantic_edits
        )
        return types.SemanticTokensDelta(edits=edits, result_id=result_id)

    def _workspace_document_state(self, uri: str) -> tuple[str, int] | None:
        try:
            text_document = cast(Any, self.workspace.get_text_document(uri))
        except KeyError:
            return None
        version = 0 if text_document.version is None else text_document.version
        return cast(str, text_document.source), cast(int, version)

    def _current_semantic_token_result(self, uri: str) -> tuple[str, tuple[int, ...]] | None:
        document = self.current_managed_document(uri)
        if document is None:
            return None

        data = encode_document_semantic_tokens(
            text=document.text,
            facts=document.facts,
            analysis=document.analysis,
        )
        result_id = self._remember_semantic_tokens(
            uri,
            version=document.version,
            data=data,
        )
        return result_id, data

    def _remember_semantic_tokens(
        self,
        uri: str,
        *,
        version: int,
        data: tuple[int, ...],
    ) -> str:
        with self._state_lock:
            cached_results = self._semantic_token_results_by_uri.setdefault(uri, OrderedDict())
            for cached_result_id, cached_result in cached_results.items():
                if cached_result.version != version or cached_result.data != data:
                    continue
                cached_results.move_to_end(cached_result_id)
                return cached_result_id

            result_id = f'tcl-ls-semantic/{self._next_semantic_token_result_id}'
            self._next_semantic_token_result_id += 1
            cached_results[result_id] = _SemanticTokenResult(version=version, data=data)
            while len(cached_results) > _SEMANTIC_TOKEN_CACHE_LIMIT:
                cached_results.popitem(last=False)
            return result_id

    def _semantic_token_data(self, uri: str, result_id: str) -> tuple[int, ...] | None:
        with self._state_lock:
            cached_results = self._semantic_token_results_by_uri.get(uri)
            if cached_results is None:
                return None
            cached_result = cached_results.get(result_id)
            if cached_result is None:
                return None
            cached_results.move_to_end(result_id)
            return cached_result.data

    def _analyze_workspace_document(
        self,
        snapshot: AnalysisSnapshot,
        *,
        uri: str,
        text: str,
        version: int,
    ) -> ManagedDocument:
        parser = Parser()
        extractor = FactExtractor(parser, metadata_registry=snapshot.metadata_registry)
        resolver = Resolver(metadata_registry=snapshot.metadata_registry)

        try:
            parse_result = parser.parse_document(path=uri, text=text)
            facts = extractor.extract(parse_result)
            managed_document = ManagedDocument(
                uri=uri,
                version=version,
                text=text,
                parse_result=parse_result,
                facts=facts,
                analysis=empty_analysis(uri, facts.document_symbols),
            )

            documents = dict(snapshot.documents)
            documents[uri] = managed_document
            document_workspace_index = analysis_workspace_index(
                root_uri=uri,
                documents=documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
            )

            source_path = source_id_to_path(uri)
            additional_required_packages: frozenset[str]
            if source_path is None:
                additional_required_packages = frozenset()
            else:
                additional_required_packages = dependency_required_packages(
                    source_path,
                    facts,
                    document_workspace_index,
                    metadata_registry=snapshot.metadata_registry,
                )
            analysis = resolver.analyze(
                uri=uri,
                facts=facts,
                workspace_index=document_workspace_index,
                additional_required_packages=additional_required_packages,
            )

            return ManagedDocument(
                uri=uri,
                version=version,
                text=text,
                parse_result=parse_result,
                facts=facts,
                analysis=analysis,
            )
        finally:
            extractor.close()

    def completion_items_at(
        self,
        snapshot: AnalysisSnapshot,
        *,
        uri: str,
        line: int,
        character: int,
    ) -> tuple[types.CompletionItem, ...]:
        with self._toolkit_lock:
            return completion_items(
                snapshot.documents,
                workspace_index=snapshot.workspace_index,
                metadata_registry=snapshot.metadata_registry,
                parser=self.parser,
                extractor=self.extractor,
                uri=uri,
                line=line,
                character=character,
            )

    def signature_help_at(
        self,
        snapshot: AnalysisSnapshot,
        *,
        uri: str,
        line: int,
        character: int,
    ) -> types.SignatureHelp | None:
        with self._toolkit_lock:
            return signature_help(
                snapshot.documents,
                metadata_registry=snapshot.metadata_registry,
                parser=self.parser,
                extractor=self.extractor,
                uri=uri,
                line=line,
                character=character,
            )

    def publish_document_diagnostics(
        self,
        uri: str,
        diagnostics: tuple[Diagnostic, ...],
    ) -> None:
        self._publish_document_diagnostics(uri, diagnostics)

    def begin_indexing_feedback(self) -> tuple[IndexingProgressCallback | None, Callable[[], None]]:
        if self._indexing_notification_shown:
            return None, lambda: None
        self._indexing_notification_shown = True

        client_capabilities = getattr(self.protocol, 'client_capabilities', None)
        if client_capabilities is None or client_capabilities.window is None:
            self.window_show_message(
                types.ShowMessageParams(
                    type=types.MessageType.Info,
                    message='Indexing workspace.',
                )
            )
            return None, lambda: None
        if not client_capabilities.window.work_done_progress:
            self.window_show_message(
                types.ShowMessageParams(
                    type=types.MessageType.Info,
                    message='Indexing workspace.',
                )
            )
            return None, lambda: None

        token = f'tcl-ls/indexing/{self._next_progress_token}'
        self._next_progress_token += 1
        request_id = f'tcl-ls/request/{self._next_server_request_id}'
        self._next_server_request_id += 1
        self.protocol.send_request(
            types.WINDOW_WORK_DONE_PROGRESS_CREATE,
            types.WorkDoneProgressCreateParams(token=token),
            msg_id=request_id,
        )
        self.work_done_progress.begin(
            token,
            types.WorkDoneProgressBegin(
                title='Indexing workspace',
                message='Starting analysis',
                percentage=0,
            ),
        )

        def report_progress(message: str, percentage: int) -> None:
            self.work_done_progress.report(
                token,
                types.WorkDoneProgressReport(
                    message=message,
                    percentage=percentage,
                ),
            )

        def finish_progress() -> None:
            self.work_done_progress.end(
                token,
                types.WorkDoneProgressEnd(message='Indexing complete.'),
            )

        return report_progress, finish_progress

    def _initialize_analysis_state(
        self,
        *,
        parser: Parser | None = None,
        extractor: FactExtractor | None = None,
        workspace_index: WorkspaceIndex | None = None,
        resolver: Resolver | None = None,
        metadata_registry: MetadataRegistry | None = None,
    ) -> None:
        extracted_metadata_registry = extractor.metadata_registry if extractor is not None else None
        resolver_metadata_registry = resolver.metadata_registry if resolver is not None else None
        resolved_metadata_registry = (
            metadata_registry
            if metadata_registry is not None
            else extracted_metadata_registry
            or resolver_metadata_registry
            or DEFAULT_METADATA_REGISTRY
        )
        if (
            extracted_metadata_registry is not None
            and extracted_metadata_registry != resolved_metadata_registry
        ):
            raise ValueError('Extractor metadata registry does not match LanguageServer.')
        if (
            resolver_metadata_registry is not None
            and resolver_metadata_registry != resolved_metadata_registry
        ):
            raise ValueError('Resolver metadata registry does not match LanguageServer.')

        self._metadata_registry = resolved_metadata_registry
        self._parser = Parser() if parser is None else parser
        self._extractor = (
            FactExtractor(self._parser, metadata_registry=self._metadata_registry)
            if extractor is None
            else extractor
        )
        self._next_semantic_token_result_id = 1
        self._semantic_token_results_by_uri = {}
        self._workspace_index = WorkspaceIndex() if workspace_index is None else workspace_index
        self._resolver = (
            Resolver(metadata_registry=self._metadata_registry) if resolver is None else resolver
        )
        self.documents = {}
        self._scanned_package_roots = set()
        self._open_document_uris = set()
        self._plugin_paths_by_uri = {}
        self._library_paths_by_uri = {}

    def _document_build_snapshot(self) -> DocumentBuildSnapshot:
        with self._state_lock:
            return DocumentBuildSnapshot(
                documents=self.documents,
                open_document_uris=tuple(self._open_document_uris),
                plugin_paths_by_uri=dict(self._plugin_paths_by_uri),
                library_paths_by_uri=dict(self._library_paths_by_uri),
            )

    def _load_documents(
        self,
        documents: Iterable[tuple[str, str, int]],
        *,
        progress: IndexingProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> bool:
        pending_documents = tuple(documents)
        with self._state_lock:
            for uri, _, _ in pending_documents:
                self._open_document_uris.add(uri)
                path = source_id_to_path(uri)
                if path is None:
                    self._plugin_paths_by_uri[uri] = ()
                    self._library_paths_by_uri[uri] = ()
                    continue
                self._plugin_paths_by_uri[uri] = configured_plugin_paths(path)
                self._library_paths_by_uri[uri] = configured_library_paths(path)

        if progress is not None:
            progress('Rebuilding workspace index', 10)

        rebuild_result = WorkspaceRebuilder(
            progress=progress,
            should_cancel=should_cancel,
        ).rebuild(
            self._document_build_snapshot(),
            pending_documents,
        )
        if rebuild_result is None:
            return False

        with self._state_lock:
            if should_cancel is not None and should_cancel():
                return False
            with self._toolkit_lock:
                self._set_metadata_registry(rebuild_result.metadata_registry)
            self.documents = rebuild_result.documents
            self._workspace_index = rebuild_result.workspace_index
            self._scanned_package_roots = rebuild_result.scanned_package_roots
        return True

    def _publish_document_diagnostics(
        self,
        uri: str,
        diagnostics: tuple[Diagnostic, ...],
    ) -> None:
        self.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                diagnostics=[
                    types.Diagnostic(
                        range=lsp_range(diagnostic.span),
                        severity=_DIAGNOSTIC_SEVERITY_MAP[diagnostic.severity],
                        code=diagnostic.code,
                        source=diagnostic.source,
                        message=diagnostic.message,
                        tags=[_DIAGNOSTIC_TAG_MAP[tag] for tag in diagnostic.tags] or None,
                    )
                    for diagnostic in diagnostics
                ],
            )
        )

    def _set_metadata_registry(self, metadata_registry: MetadataRegistry) -> None:
        if metadata_registry == self._metadata_registry:
            return

        self._extractor.close()
        self._metadata_registry = metadata_registry
        self._extractor = FactExtractor(self._parser, metadata_registry=metadata_registry)
        self._resolver = Resolver(metadata_registry=metadata_registry)


class _TclLanguageServerProtocol(LanguageServerProtocol):
    def reset_runtime_state(self) -> None:
        self.writer = None
        self._include_headers = False
        self._shutdown = False
        self._workspace = None

        for future in self._request_futures.values():
            if not future.done():
                future.cancel()
        self._request_futures.clear()
        self._result_types.clear()

        progress_tokens = cast(
            dict[types.ProgressToken, Future[Any]],
            self.progress.tokens,  # pyright: ignore[reportUnknownMemberType]
        )
        for future in progress_tokens.values():
            if not future.done():
                future.cancel()
        progress_tokens.clear()

        self.__dict__.pop('client_capabilities', None)
        self.__dict__.pop('server_capabilities', None)


server = LanguageServer()


@server.feature(types.INITIALIZED)
def initialized(server: LanguageServer, params: types.InitializedParams) -> None:
    del params
    server.window_log_message(
        types.LogMessageParams(
            type=types.MessageType.Info,
            message='tcl-ls started.',
        )
    )


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(server: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    uri = params.text_document.uri
    progress, finish_progress = server.begin_indexing_feedback()
    try:
        diagnostics = server.open_document(
            uri=uri,
            text=params.text_document.text,
            version=params.text_document.version,
            progress=progress,
        )
        server.window_log_message(
            types.LogMessageParams(
                type=types.MessageType.Info,
                message=f'Indexing workspace for {uri}.',
            )
        )
        server.publish_document_diagnostics(uri, diagnostics)
    finally:
        finish_progress()


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    server.schedule_document_change(
        uri=params.text_document.uri,
        version=params.text_document.version,
    )


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(server: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    server.close_document(uri)
    server.publish_document_diagnostics(uri, ())


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition_request(
    server: LanguageServer,
    params: types.DefinitionParams,
) -> list[types.Location] | None:
    snapshot = server.analysis_snapshot()
    locations = definition(
        snapshot.documents,
        workspace_index=snapshot.workspace_index,
        metadata_registry=snapshot.metadata_registry,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
    )
    return list(locations) or None


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references_request(
    server: LanguageServer,
    params: types.ReferenceParams,
) -> list[types.Location]:
    snapshot = server.analysis_snapshot()
    locations = references(
        snapshot.documents,
        metadata_registry=snapshot.metadata_registry,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
        include_declaration=params.context.include_declaration,
    )
    return list(locations)


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename_request(
    server: LanguageServer, params: types.RenameParams
) -> types.WorkspaceEdit | None:
    snapshot = server.analysis_snapshot()
    edits = rename(
        snapshot.documents,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
        new_name=params.new_name,
    )
    if edits is None:
        return None

    return types.WorkspaceEdit(
        changes={
            uri: [
                types.TextEdit(
                    range=lsp_range(edit.span),
                    new_text=edit.new_text,
                )
                for edit in uri_edits
            ]
            for uri, uri_edits in edits.items()
        }
    )


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover_request(server: LanguageServer, params: types.HoverParams) -> types.Hover | None:
    snapshot = server.analysis_snapshot()
    hover_info = hover(
        snapshot.documents,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
    )
    if hover_info is None:
        return None

    signature, separator, remainder = hover_info.contents.partition('\n\n')
    contents = hover_info.contents
    if signature.startswith('proc '):
        contents = (
            f'```tcl\n{signature}\n```'
            if not separator
            else f'```tcl\n{signature}\n```\n\n{remainder}'
        )
    elif signature.startswith('builtin command '):
        command_name = signature.removeprefix('builtin command ')
        contents = (
            f'```tcl\n{command_name}\n```'
            if not separator
            else f'```tcl\n{command_name}\n```\n\n{remainder}'
        )
    elif '\n' in hover_info.contents and not separator:
        contents = f'```tcl\n{hover_info.contents}\n```'

    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=contents,
        ),
        range=lsp_range(hover_info.span),
    )


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=['$', ':', '-']),
)
def completion_request(
    server: LanguageServer,
    params: types.CompletionParams,
) -> types.CompletionList:
    snapshot = server.analysis_snapshot()
    items = server.completion_items_at(
        snapshot,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
    )
    return types.CompletionList(is_incomplete=False, items=list(items))


@server.feature(
    types.TEXT_DOCUMENT_SIGNATURE_HELP,
    types.SignatureHelpOptions(trigger_characters=[' ', '\t']),
)
def signature_help_request(
    server: LanguageServer,
    params: types.SignatureHelpParams,
) -> types.SignatureHelp | None:
    snapshot = server.analysis_snapshot()
    return server.signature_help_at(
        snapshot,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight_request(
    server: LanguageServer,
    params: types.DocumentHighlightParams,
) -> list[types.DocumentHighlight]:
    snapshot = server.analysis_snapshot()
    return list(
        document_highlights(
            snapshot.documents,
            uri=params.text_document.uri,
            line=params.position.line,
            character=params.position.character,
        )
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbols(
    server: LanguageServer,
    params: types.DocumentSymbolParams,
) -> list[types.DocumentSymbol]:
    document = server.analysis_snapshot().documents.get(params.text_document.uri)
    if document is None:
        return []
    return list(document.analysis.document_symbols)


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    types.SemanticTokensLegend(
        token_types=list(SEMANTIC_TOKEN_TYPES),
        token_modifiers=list(SEMANTIC_TOKEN_MODIFIERS),
    ),
)
def semantic_tokens_full(
    server: LanguageServer,
    params: types.SemanticTokensParams,
) -> types.SemanticTokens | None:
    return server.semantic_tokens(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL_DELTA)
def semantic_tokens_full_delta(
    server: LanguageServer,
    params: types.SemanticTokensDeltaParams,
) -> types.SemanticTokens | types.SemanticTokensDelta | None:
    return server.semantic_token_delta(
        params.text_document.uri,
        params.previous_result_id,
    )


@server.feature(types.WORKSPACE_SYMBOL)
def workspace_symbol_request(
    server: LanguageServer,
    params: types.WorkspaceSymbolParams,
) -> list[types.WorkspaceSymbol]:
    return list(workspace_symbols(server.analysis_snapshot().documents, query=params.query))
