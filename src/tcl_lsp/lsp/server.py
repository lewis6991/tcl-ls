from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, cast

from lsprotocol import types
from pygls.lsp.server import LanguageServer as PyglsLanguageServer
from pygls.protocol.language_server import LanguageServerProtocol

from tcl_lsp import __version__
from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.common import Diagnostic, lsp_range
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
    encode_document_semantic_tokens,
)
from tcl_lsp.lsp.state import (
    IndexingProgressCallback,
    ManagedDocument,
    empty_analysis,
    managed_document_details,
)
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataRegistry,
    create_metadata_registry,
)
from tcl_lsp.parser import Parser
from tcl_lsp.project.config import configured_library_paths, configured_plugin_paths
from tcl_lsp.project.indexing import (
    load_dependency_documents,
    reachable_document_uris,
    scan_package_root,
)
from tcl_lsp.project.paths import candidate_package_roots, read_source_file, source_id_to_path

_DIAGNOSTIC_SEVERITY_MAP = {
    'error': types.DiagnosticSeverity.Error,
    'warning': types.DiagnosticSeverity.Warning,
    'information': types.DiagnosticSeverity.Information,
    'hint': types.DiagnosticSeverity.Hint,
}


class LanguageServer(PyglsLanguageServer):
    documents: dict[str, ManagedDocument]
    _extractor: FactExtractor
    _indexing_notification_shown: bool
    _library_paths_by_uri: dict[str, tuple[Path, ...]]
    _metadata_registry: MetadataRegistry
    _next_progress_token: int
    _next_server_request_id: int
    _open_document_uris: set[str]
    _parser: Parser
    _plugin_paths_by_uri: dict[str, tuple[Path, ...]]
    _resolver: Resolver
    _scanned_package_roots: set[Path]
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

    def open_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),), progress=progress)
        document = self.documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),))
        document = self.documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def close_document(self, uri: str) -> None:
        if uri not in self.documents:
            return

        self._open_document_uris.discard(uri)
        self._plugin_paths_by_uri.pop(uri, None)
        self._library_paths_by_uri.pop(uri, None)
        self._rebuild_documents()

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

    def load_documents(
        self,
        documents: Iterable[tuple[str, str, int]],
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> None:
        pending_documents = tuple(documents)
        if not pending_documents:
            return

        for uri, _, _ in pending_documents:
            self._open_document_uris.add(uri)
            path = source_id_to_path(uri)
            if path is None:
                self._plugin_paths_by_uri[uri] = ()
                self._library_paths_by_uri[uri] = ()
                continue
            self._plugin_paths_by_uri[uri] = configured_plugin_paths(path)
            self._library_paths_by_uri[uri] = configured_library_paths(path)

        self._report_progress(progress, 'Rebuilding workspace index', 10)
        self._rebuild_documents(pending_documents, progress=progress)

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
        self._workspace_index = WorkspaceIndex() if workspace_index is None else workspace_index
        self._resolver = (
            Resolver(metadata_registry=self._metadata_registry) if resolver is None else resolver
        )
        self.documents = {}
        self._scanned_package_roots = set()
        self._open_document_uris = set()
        self._plugin_paths_by_uri = {}
        self._library_paths_by_uri = {}

    def _build_document(self, *, uri: str, text: str, version: int) -> ManagedDocument:
        parse_result = self._parser.parse_document(path=uri, text=text)
        facts = self._extractor.extract(parse_result)
        return ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            parse_result=parse_result,
            facts=facts,
            analysis=empty_analysis(uri, facts.document_symbols),
        )

    def _discover_package_roots(self, uri: str) -> None:
        path = source_id_to_path(uri)
        if path is None:
            return

        package_roots = (*candidate_package_roots(path), *self._library_paths_by_uri.get(uri, ()))
        for package_root in package_roots:
            resolved_root = package_root.resolve(strict=False)
            if resolved_root in self._scanned_package_roots:
                continue
            self._scanned_package_roots.add(resolved_root)
            scan_package_root(
                resolved_root,
                parser=self._parser,
                extractor=self._extractor,
                workspace_index=self._workspace_index,
            )

    def _ensure_background_documents_loaded(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        start_percentage: int = 50,
        end_percentage: int = 75,
    ) -> None:
        def load_document(uri: str) -> ManagedDocument | None:
            path = source_id_to_path(uri)
            if path is None:
                return None

            try:
                text = read_source_file(path)
            except OSError:
                return None

            return self._build_document(uri=uri, text=text, version=0)

        loaded_documents = load_dependency_documents(
            self.documents,
            workspace_index=self._workspace_index,
            describe_document=managed_document_details,
            load_document=load_document,
            metadata_registry=self._metadata_registry,
            on_document_loaded=lambda document: self._discover_package_roots(document.uri),
        )

        loaded_background_documents = 0
        for _ in loaded_documents:
            loaded_background_documents += 1
            self._report_progress(
                progress,
                f'Loading workspace dependencies ({loaded_background_documents})',
                min(end_percentage, start_percentage + loaded_background_documents),
            )

    def _recompute_workspace_analyses(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        start_percentage: int = 75,
        end_percentage: int = 95,
    ) -> None:
        documents = list(self.documents.items())
        total_documents = len(documents)
        for index, (uri, document) in enumerate(documents, start=1):
            analysis_workspace_index = self._analysis_workspace_index(uri)
            source_path = source_id_to_path(uri)
            additional_required_packages: frozenset[str]
            if source_path is None:
                additional_required_packages = frozenset()
            else:
                additional_required_packages = dependency_required_packages(
                    source_path,
                    document.facts,
                    analysis_workspace_index,
                    metadata_registry=self._metadata_registry,
                )
            analysis = self._resolver.analyze(
                uri=uri,
                facts=document.facts,
                workspace_index=analysis_workspace_index,
                additional_required_packages=additional_required_packages,
            )
            self.documents[uri] = ManagedDocument(
                uri=document.uri,
                version=document.version,
                text=document.text,
                parse_result=document.parse_result,
                facts=document.facts,
                analysis=analysis,
            )
            self._report_progress(
                progress,
                f'Analyzing workspace ({index}/{total_documents})',
                _progress_percentage(
                    index=index,
                    total=total_documents,
                    start=start_percentage,
                    end=end_percentage,
                ),
            )

    def _analysis_workspace_index(self, root_uri: str) -> WorkspaceIndex:
        workspace_index = WorkspaceIndex()
        for pkg_index_uri, entries in self._workspace_index.package_indexes():
            workspace_index.update_package_index(pkg_index_uri, entries)
        for uri in reachable_document_uris(
            root_uri,
            documents_by_uri=self.documents,
            workspace_index=self._workspace_index,
            describe_document=managed_document_details,
            metadata_registry=self._metadata_registry,
        ):
            document = self.documents.get(uri)
            if document is None:
                continue
            workspace_index.update(uri, document.facts)
        return workspace_index

    def _rebuild_documents(
        self,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> None:
        snapshots: dict[str, tuple[str, int]] = {}
        for uri in self._open_document_uris:
            document = self.documents.get(uri)
            if document is None:
                continue
            snapshots[uri] = (document.text, document.version)
        for uri, text, version in pending_documents:
            snapshots[uri] = (text, version)

        self._set_metadata_registry(create_metadata_registry(self._active_plugin_paths()))

        self.documents = {}
        self._workspace_index = WorkspaceIndex()
        self._scanned_package_roots = set()

        total_snapshots = len(snapshots)
        for index, (uri, (text, version)) in enumerate(snapshots.items(), start=1):
            document = self._build_document(uri=uri, text=text, version=version)
            self.documents[uri] = document
            self._workspace_index.update(uri, document.facts)
            self._discover_package_roots(uri)
            self._report_progress(
                progress,
                f'Indexing workspace files ({index}/{total_snapshots})',
                _progress_percentage(
                    index=index,
                    total=total_snapshots,
                    start=20,
                    end=45,
                ),
            )

        self._report_progress(progress, 'Loading workspace dependencies', 50)
        self._ensure_background_documents_loaded(
            progress=progress,
            start_percentage=50,
            end_percentage=75,
        )
        self._recompute_workspace_analyses(
            progress=progress,
            start_percentage=75,
            end_percentage=95,
        )

    def _report_progress(
        self,
        progress: IndexingProgressCallback | None,
        message: str,
        percentage: int,
    ) -> None:
        if progress is None:
            return
        progress(message, percentage)

    def _active_plugin_paths(self) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in self._open_document_uris:
            for plugin_path in self._plugin_paths_by_uri.get(uri, ()):
                active_paths.setdefault(plugin_path, None)
        return tuple(active_paths)

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
        server.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                diagnostics=[
                    types.Diagnostic(
                        range=lsp_range(diagnostic.span),
                        severity=_DIAGNOSTIC_SEVERITY_MAP[diagnostic.severity],
                        code=diagnostic.code,
                        source=diagnostic.source,
                        message=diagnostic.message,
                    )
                    for diagnostic in diagnostics
                ],
            )
        )
    finally:
        finish_progress()


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(server: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    uri = params.text_document.uri
    document = server.workspace.get_text_document(uri)
    diagnostics = server.change_document(
        uri=uri,
        text=document.source,
        version=params.text_document.version,
    )
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=uri,
            diagnostics=[
                types.Diagnostic(
                    range=lsp_range(diagnostic.span),
                    severity=_DIAGNOSTIC_SEVERITY_MAP[diagnostic.severity],
                    code=diagnostic.code,
                    source=diagnostic.source,
                    message=diagnostic.message,
                )
                for diagnostic in diagnostics
            ],
        )
    )


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(server: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    server.close_document(uri)
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition_request(
    server: LanguageServer,
    params: types.DefinitionParams,
) -> list[types.Location] | None:
    locations = definition(
        server.documents,
        workspace_index=server.workspace_index,
        metadata_registry=server.metadata_registry,
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
    locations = references(
        server.documents,
        metadata_registry=server.metadata_registry,
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
    edits = rename(
        server.documents,
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
    hover_info = hover(
        server.documents,
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
    types.CompletionOptions(trigger_characters=['$', ':']),
)
def completion_request(
    server: LanguageServer,
    params: types.CompletionParams,
) -> types.CompletionList:
    items = completion_items(
        server.documents,
        workspace_index=server.workspace_index,
        metadata_registry=server.metadata_registry,
        parser=server.parser,
        extractor=server.extractor,
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
    return signature_help(
        server.documents,
        metadata_registry=server.metadata_registry,
        parser=server.parser,
        extractor=server.extractor,
        uri=params.text_document.uri,
        line=params.position.line,
        character=params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight_request(
    server: LanguageServer,
    params: types.DocumentHighlightParams,
) -> list[types.DocumentHighlight]:
    return list(
        document_highlights(
            server.documents,
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
    document = server.documents.get(params.text_document.uri)
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
    document = server.documents.get(params.text_document.uri)
    if document is None:
        return None
    data = encode_document_semantic_tokens(
        text=document.text,
        facts=document.facts,
        analysis=document.analysis,
    )
    return types.SemanticTokens(data=list(data))


@server.feature(types.WORKSPACE_SYMBOL)
def workspace_symbol_request(
    server: LanguageServer,
    params: types.WorkspaceSymbolParams,
) -> list[types.WorkspaceSymbol]:
    return list(workspace_symbols(server.documents, query=params.query))


def _progress_percentage(*, index: int, total: int, start: int, end: int) -> int:
    if total <= 0 or start >= end:
        return end
    completed = (index * (end - start)) // total
    return min(end, start + completed)
