from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.analysis import DocumentFacts, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.facts.bodies import BodyAnalysisCache
from tcl_lsp.analysis.facts.lowering import DocumentSyntax
from tcl_lsp.analysis.types import CallTypes
from tcl_lsp.lsp.features.symbols import reference_command_names
from tcl_lsp.lsp.state import (
    IndexingProgressCallback,
    ManagedDocument,
    ReferenceQuery,
    empty_analysis,
    managed_document_details,
)
from tcl_lsp.metadata_paths import MetadataRegistry, create_metadata_registry
from tcl_lsp.parser import Parser
from tcl_lsp.project.declarations import MetadataPath
from tcl_lsp.project.indexing import (
    dependency_source_uris_for_facts,
    discover_lazy_package_indexes,
    load_package_index,
    prepare_dependencies,
    reachable_document_uris,
)
from tcl_lsp.project.paths import (
    FileRevision,
    candidate_package_roots,
    file_revision,
    read_source_file,
    source_id_to_path,
)

type CancelCallback = Callable[[], bool]
type CachedDocumentLoader = Callable[[str, Resolver | None], ManagedDocument | None]
type CachedDocumentSaver = Callable[[ManagedDocument], None]


@dataclass(frozen=True, slots=True)
class DocumentBuildSnapshot:
    documents: dict[str, ManagedDocument]
    open_document_uris: tuple[str, ...]
    metadata_paths_by_uri: dict[str, tuple[MetadataPath, ...]]
    library_paths_by_uri: dict[str, tuple[Path, ...]]
    workspace_index: WorkspaceIndex
    scanned_package_roots: tuple[Path, ...]
    configuration_revision: FileRevision = ()
    configuration_roots: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class RebuildResult:
    documents: dict[str, ManagedDocument]
    workspace_index: WorkspaceIndex
    scanned_package_roots: set[Path]
    metadata_registry: MetadataRegistry

    def disk_revision(self, open_uris: tuple[str, ...]) -> FileRevision:
        uris = dict.fromkeys(uri for uri in self.documents if uri not in open_uris)
        # Track missing source targets too, so their creation invalidates reuse.
        for document in self.documents.values():
            uris.update(
                dict.fromkeys(
                    dependency_source_uris_for_facts(
                        source_id_to_path(document.uri),
                        document.facts,
                        self.workspace_index,
                        metadata_registry=self.metadata_registry,
                    )
                )
            )
        return file_revision(
            path
            for uri in uris
            if uri not in open_uris
            if (path := source_id_to_path(uri)) is not None
        )


class _AnalysisCancelled(RuntimeError):
    pass


class WorkspaceRebuilder:
    _progress: IndexingProgressCallback | None
    _should_cancel: CancelCallback | None

    def __init__(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        metadata_registry: MetadataRegistry | None = None,
        reuse_documents: Mapping[str, ManagedDocument] | None = None,
        include_diagnostics: bool = True,
        reference_query: ReferenceQuery | None = None,
    ) -> None:
        self._progress = progress
        self._should_cancel = should_cancel
        self._metadata_registry = metadata_registry
        self._reuse_documents = reuse_documents or {}
        self._include_diagnostics = include_diagnostics
        self._reference_query = reference_query

    def rebuild(
        self,
        snapshot: DocumentBuildSnapshot,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        load_cached_document: CachedDocumentLoader | None = None,
        cache_document: CachedDocumentSaver | None = None,
    ) -> RebuildResult | None:
        target_metadata_registry = self._metadata_registry or create_metadata_registry(
            self._active_metadata_paths(snapshot),
            configuration_roots=snapshot.configuration_roots,
        )
        parser = Parser()
        extractor = FactExtractor(parser, metadata_registry=target_metadata_registry)
        resolver = Resolver(metadata_registry=target_metadata_registry)

        try:
            self._raise_if_cancelled()

            snapshots: dict[str, tuple[str, int]] = {}
            for uri in snapshot.open_document_uris:
                document = snapshot.documents.get(uri)
                if document is None:
                    continue
                snapshots[uri] = (document.text, document.version)
            for uri, text, version in pending_documents:
                snapshots[uri] = (text, version)

            documents: dict[str, ManagedDocument] = {}
            workspace_index = WorkspaceIndex()
            scanned_package_roots: set[Path] = set()

            total_snapshots = len(snapshots)
            for index, (uri, (text, version)) in enumerate(snapshots.items(), start=1):
                self._raise_if_cancelled()
                document = self._build_document(
                    parser=parser,
                    extractor=extractor,
                    uri=uri,
                    text=text,
                    version=version,
                    previous=self._reuse_documents.get(uri),
                )
                documents[uri] = document
                workspace_index.update(uri, document.facts)
                self._discover_package_roots(
                    uri=uri,
                    workspace_index=workspace_index,
                    scanned_package_roots=scanned_package_roots,
                    library_paths_by_uri=snapshot.library_paths_by_uri,
                )
                self._report_progress(
                    f'Indexing workspace files ({index}/{total_snapshots})',
                    _progress_percentage(
                        index=index,
                        total=total_snapshots,
                        start=20,
                        end=45,
                    ),
                )

            self._report_progress('Loading workspace dependencies', 50)
            self._ensure_background_documents_loaded(
                documents,
                parser=parser,
                extractor=extractor,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                library_paths_by_uri=snapshot.library_paths_by_uri,
                start_percentage=50,
                end_percentage=75,
                load_cached_document=load_cached_document,
                cache_document=cache_document,
            )
            self._prune_background_documents(
                documents,
                open_document_uris=tuple(snapshots),
                workspace_index=workspace_index,
                metadata_registry=target_metadata_registry,
            )
            self._recompute_analyses(
                documents,
                document_uris=tuple(documents),
                resolver=resolver,
                workspace_index=workspace_index,
                metadata_registry=target_metadata_registry,
                start_percentage=75,
                end_percentage=95,
            )
            self._raise_if_cancelled()
            return RebuildResult(
                documents=documents,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                metadata_registry=target_metadata_registry,
            )
        except _AnalysisCancelled:
            return None
        finally:
            extractor.close()

    def reanalyze(self, result: RebuildResult) -> RebuildResult | None:
        """Reuse prepared facts when only the reference position has changed."""
        documents = dict(result.documents)
        try:
            self._recompute_analyses(
                documents,
                document_uris=tuple(documents),
                resolver=Resolver(metadata_registry=result.metadata_registry),
                workspace_index=result.workspace_index,
                metadata_registry=result.metadata_registry,
                start_percentage=75,
                end_percentage=95,
            )
            self._raise_if_cancelled()
        except _AnalysisCancelled:
            return None
        return replace(result, documents=documents)

    def incremental_rebuild(
        self,
        snapshot: DocumentBuildSnapshot,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        load_cached_document: CachedDocumentLoader | None = None,
        cache_document: CachedDocumentSaver | None = None,
    ) -> RebuildResult | None:
        target_metadata_registry = self._metadata_registry or create_metadata_registry(
            self._active_metadata_paths(snapshot),
            configuration_roots=snapshot.configuration_roots,
        )
        parser = Parser()
        extractor = FactExtractor(parser, metadata_registry=target_metadata_registry)
        resolver = Resolver(metadata_registry=target_metadata_registry)

        try:
            self._raise_if_cancelled()

            documents = dict(snapshot.documents)
            workspace_index = _copy_workspace_index(snapshot.workspace_index)
            scanned_package_roots = set(snapshot.scanned_package_roots)
            pending_snapshots = tuple(pending_documents)

            total_snapshots = len(pending_snapshots)
            for index, (uri, text, version) in enumerate(pending_snapshots, start=1):
                self._raise_if_cancelled()
                document = self._build_document(
                    parser=parser,
                    extractor=extractor,
                    uri=uri,
                    text=text,
                    version=version,
                    previous=documents.get(uri),
                )
                documents[uri] = document
                workspace_index.update(uri, document.facts)
                self._discover_package_roots(
                    uri=uri,
                    workspace_index=workspace_index,
                    scanned_package_roots=scanned_package_roots,
                    library_paths_by_uri=snapshot.library_paths_by_uri,
                )
                self._report_progress(
                    f'Indexing workspace files ({index}/{total_snapshots})',
                    _progress_percentage(
                        index=index,
                        total=total_snapshots,
                        start=20,
                        end=45,
                    ),
                )

            self._prune_background_documents(
                documents,
                open_document_uris=snapshot.open_document_uris,
                workspace_index=workspace_index,
                metadata_registry=target_metadata_registry,
            )

            self._report_progress('Loading workspace dependencies', 50)
            self._ensure_background_documents_loaded(
                documents,
                parser=parser,
                extractor=extractor,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                library_paths_by_uri=snapshot.library_paths_by_uri,
                start_percentage=50,
                end_percentage=75,
                background_resolver=resolver,
                load_cached_document=load_cached_document,
                cache_document=cache_document,
            )
            self._prune_background_documents(
                documents,
                open_document_uris=snapshot.open_document_uris,
                workspace_index=workspace_index,
                metadata_registry=target_metadata_registry,
            )
            self._recompute_analyses(
                documents,
                document_uris=snapshot.open_document_uris,
                resolver=resolver,
                workspace_index=workspace_index,
                metadata_registry=target_metadata_registry,
                start_percentage=75,
                end_percentage=95,
            )
            self._raise_if_cancelled()
            return RebuildResult(
                documents=documents,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                metadata_registry=target_metadata_registry,
            )
        except _AnalysisCancelled:
            return None
        finally:
            extractor.close()

    def _build_document(
        self,
        *,
        parser: Parser,
        extractor: FactExtractor,
        uri: str,
        text: str,
        version: int,
        background_resolver: Resolver | None = None,
        include_lexical_spans: bool = False,
        previous: ManagedDocument | None = None,
    ) -> ManagedDocument:
        if (
            previous is not None
            and previous.text == text
            and (previous.lexical_spans_included or not include_lexical_spans)
        ):
            return replace(previous, version=version)

        parse_result = parser.parse_document(path=uri, text=text)
        syntax = DocumentSyntax(
            parse_result, parser=parser, previous=previous.syntax if previous is not None else None
        )
        body_cache = previous.body_cache.fork() if previous is not None else BodyAnalysisCache()
        facts = extractor.extract(
            parse_result,
            syntax=syntax,
            body_cache=body_cache,
            include_lexical_spans=include_lexical_spans,
        )
        return ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            syntax=syntax,
            body_cache=body_cache,
            facts=facts,
            analysis=(
                empty_analysis(uri, facts.document_symbols)
                if background_resolver is None
                else background_resolver.facts_only_analysis(uri, facts)
            ),
            lexical_spans_included=include_lexical_spans,
        )

    def _discover_package_roots(
        self,
        *,
        uri: str,
        workspace_index: WorkspaceIndex,
        scanned_package_roots: set[Path],
        library_paths_by_uri: dict[str, tuple[Path, ...]],
    ) -> None:
        self._raise_if_cancelled()

        path = source_id_to_path(uri)
        if path is None:
            return

        package_roots = (*candidate_package_roots(path), *library_paths_by_uri.get(uri, ()))
        for package_root in package_roots:
            self._raise_if_cancelled()
            resolved_root = package_root.resolve(strict=False)
            if resolved_root in scanned_package_roots:
                continue
            scanned_package_roots.add(resolved_root)
            workspace_index.register_lazy_package_indexes(
                discover_lazy_package_indexes(resolved_root),
                load_package_index=load_package_index,
            )

    def _ensure_background_documents_loaded(
        self,
        documents: dict[str, ManagedDocument],
        *,
        parser: Parser,
        extractor: FactExtractor,
        workspace_index: WorkspaceIndex,
        scanned_package_roots: set[Path],
        library_paths_by_uri: dict[str, tuple[Path, ...]],
        start_percentage: int,
        end_percentage: int,
        background_resolver: Resolver | None = None,
        load_cached_document: CachedDocumentLoader | None = None,
        cache_document: CachedDocumentSaver | None = None,
    ) -> None:
        def load_document(uri: str) -> ManagedDocument | None:
            self._raise_if_cancelled()

            path = source_id_to_path(uri)
            if path is None:
                return None

            if load_cached_document is not None:
                cached_document = load_cached_document(uri, background_resolver)
                if cached_document is not None:
                    return cached_document

            try:
                text = read_source_file(path)
            except OSError:
                return None

            document = self._build_document(
                parser=parser,
                extractor=extractor,
                uri=uri,
                text=text,
                version=0,
                background_resolver=background_resolver,
                include_lexical_spans=False,
            )
            if cache_document is not None:
                cache_document(document)
            return document

        def on_document_loaded(document: ManagedDocument) -> None:
            self._discover_package_roots(
                uri=document.uri,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                library_paths_by_uri=library_paths_by_uri,
            )

        loaded_documents = prepare_workspace_documents(
            documents,
            extractor=extractor,
            workspace_index=workspace_index,
            load_document=load_document,
            on_document_loaded=on_document_loaded,
            check_cancelled=self._raise_if_cancelled,
        )

        loaded_background_documents = 0
        for _ in loaded_documents:
            self._raise_if_cancelled()
            loaded_background_documents += 1
            self._report_progress(
                f'Loading workspace dependencies ({loaded_background_documents})',
                min(end_percentage, start_percentage + loaded_background_documents),
            )

    def _prune_background_documents(
        self,
        documents: dict[str, ManagedDocument],
        *,
        open_document_uris: tuple[str, ...],
        workspace_index: WorkspaceIndex,
        metadata_registry: MetadataRegistry,
    ) -> None:
        reachable_uris: dict[str, None] = {}
        for uri in open_document_uris:
            for reachable_uri in reachable_document_uris(
                uri,
                documents_by_uri=documents,
                workspace_index=workspace_index,
                describe_document=managed_document_details,
                metadata_registry=metadata_registry,
            ):
                reachable_uris.setdefault(reachable_uri, None)

        for uri in tuple(documents):
            if uri in reachable_uris:
                continue
            documents.pop(uri, None)
            workspace_index.remove(uri)

    def _recompute_analyses(
        self,
        documents: dict[str, ManagedDocument],
        *,
        document_uris: tuple[str, ...],
        resolver: Resolver,
        workspace_index: WorkspaceIndex,
        metadata_registry: MetadataRegistry,
        start_percentage: int,
        end_percentage: int,
    ) -> None:
        selected_documents = [documents[uri] for uri in document_uris if uri in documents]
        query = self._reference_query
        if query is not None:
            # Resolve the requested file against the rebuilt dependencies first.
            # The resulting command name can then limit work in other files.
            selected_documents.sort(key=lambda document: document.uri != query.uri)
        command_names: frozenset[str] | None = None
        total_documents = len(selected_documents)
        for index, document in enumerate(selected_documents, start=1):
            self._raise_if_cancelled()
            analysis_index = analysis_workspace_index(
                root_uri=document.uri,
                documents=documents,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
            )
            if command_names is None:
                analysis = resolver.analyze(
                    uri=document.uri,
                    facts=document.facts,
                    workspace_index=analysis_index,
                    include_diagnostics=self._include_diagnostics,
                )
            else:
                analysis = resolver.analyze_command_references(
                    document.uri, document.facts, analysis_index, command_names
                )
            document = replace(document, analysis=analysis)
            documents[document.uri] = document
            if query is not None and document.uri == query.uri:
                command_names = reference_command_names(
                    document, line=query.line, character=query.character
                )
            self._report_progress(
                f'Analyzing workspace ({index}/{total_documents})',
                _progress_percentage(
                    index=index,
                    total=total_documents,
                    start=start_percentage,
                    end=end_percentage,
                ),
            )

    def _active_metadata_paths(self, snapshot: DocumentBuildSnapshot) -> tuple[MetadataPath, ...]:
        active_paths: dict[MetadataPath, None] = {}
        for uri in snapshot.open_document_uris:
            for metadata_path in snapshot.metadata_paths_by_uri.get(uri, ()):
                active_paths.setdefault(metadata_path, None)
        return tuple(active_paths)

    def _raise_if_cancelled(self) -> None:
        if self._should_cancel is not None and self._should_cancel():
            raise _AnalysisCancelled()

    def _report_progress(self, message: str, percentage: int) -> None:
        if self._progress is None:
            return
        self._progress(message, percentage)


def _progress_percentage(*, index: int, total: int, start: int, end: int) -> int:
    if total <= 0 or start >= end:
        return end
    completed = (index * (end - start)) // total
    return min(end, start + completed)


def prepare_workspace_documents(
    documents: dict[str, ManagedDocument],
    *,
    extractor: FactExtractor,
    workspace_index: WorkspaceIndex,
    load_document: Callable[[str], ManagedDocument | None] | None = None,
    on_document_loaded: Callable[[ManagedDocument], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> tuple[ManagedDocument, ...]:
    base_facts = {uri: document.base_facts or document.facts for uri, document in documents.items()}
    facts_by_uri = dict(base_facts)
    loaded_uris: list[str] = []

    def load_facts(uri: str) -> DocumentFacts | None:
        document = load_document(uri) if load_document is not None else None
        if document is None:
            return None
        documents[document.uri] = document
        base_facts[document.uri] = document.base_facts or document.facts
        loaded_uris.append(document.uri)
        if on_document_loaded is not None:
            on_document_loaded(document)
        return base_facts[document.uri]

    def extract_facts(
        facts: DocumentFacts, packages: frozenset[str], call_types: CallTypes
    ) -> DocumentFacts:
        document = documents[facts.uri]
        # Rebuilds with new metadata replace the documents. Within this snapshot,
        # prepared facts can be reused once packages and resolved call types match.
        if packages == document.facts.required_packages and call_types == document.facts.call_types:
            return document.facts
        prepared = extractor.extract(
            document.parse_result,
            syntax=document.syntax,
            body_cache=document.body_cache,
            include_lexical_spans=False,
            module_rules=facts.module_rules,
            required_packages=packages,
            call_types=call_types,
        )
        if document.lexical_spans_included:
            comments, strings, operators = document.syntax.lexical_spans()
            prepared = replace(
                prepared,
                comment_spans=comments,
                string_spans=strings,
                operator_spans=operators,
            )
        return prepared

    prepare_dependencies(
        facts_by_uri,
        workspace_index=workspace_index,
        load_facts=load_facts,
        extract_facts=extract_facts,
        metadata_registry=extractor.metadata_registry,
        check_cancelled=check_cancelled,
        dependency_scoped_calls=True,
    )
    resolver = Resolver(metadata_registry=extractor.metadata_registry)
    for uri, facts in facts_by_uri.items():
        document = documents[uri]
        if facts is not document.facts:
            documents[uri] = replace(
                document,
                facts=facts,
                base_facts=base_facts[uri],
                analysis=resolver.facts_only_analysis(uri, facts),
            )
    return tuple(documents[uri] for uri in loaded_uris)


def analysis_workspace_index(
    *,
    root_uri: str,
    documents: dict[str, ManagedDocument],
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
) -> WorkspaceIndex:
    analysis_index = workspace_index.clone(include_documents=False)
    for uri in reachable_document_uris(
        root_uri,
        documents_by_uri=documents,
        workspace_index=workspace_index,
        describe_document=managed_document_details,
        metadata_registry=metadata_registry,
    ):
        document = documents.get(uri)
        if document is None:
            continue
        analysis_index.update(uri, document.facts)
    return analysis_index


def _copy_workspace_index(workspace_index: WorkspaceIndex) -> WorkspaceIndex:
    return workspace_index.clone()
