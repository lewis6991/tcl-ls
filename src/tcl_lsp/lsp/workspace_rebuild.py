from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.analysis import DocumentFacts, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.lsp.state import (
    IndexingProgressCallback,
    ManagedDocument,
    empty_analysis,
    managed_document_details,
)
from tcl_lsp.metadata_paths import MetadataRegistry, create_metadata_registry
from tcl_lsp.parser import Parser
from tcl_lsp.project.indexing import (
    discover_lazy_package_indexes,
    load_package_index,
    prepare_dependencies,
    reachable_document_uris,
)
from tcl_lsp.project.paths import candidate_package_roots, read_source_file, source_id_to_path

type CancelCallback = Callable[[], bool]
type CachedDocumentLoader = Callable[[str, Resolver | None], ManagedDocument | None]
type CachedDocumentSaver = Callable[[ManagedDocument], None]


@dataclass(frozen=True, slots=True)
class DocumentBuildSnapshot:
    documents: dict[str, ManagedDocument]
    open_document_uris: tuple[str, ...]
    metadata_paths_by_uri: dict[str, tuple[Path, ...]]
    library_paths_by_uri: dict[str, tuple[Path, ...]]
    workspace_index: WorkspaceIndex
    scanned_package_roots: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RebuildResult:
    documents: dict[str, ManagedDocument]
    workspace_index: WorkspaceIndex
    scanned_package_roots: set[Path]
    metadata_registry: MetadataRegistry


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
    ) -> None:
        self._progress = progress
        self._should_cancel = should_cancel

    def rebuild(
        self,
        snapshot: DocumentBuildSnapshot,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        load_cached_document: CachedDocumentLoader | None = None,
        cache_document: CachedDocumentSaver | None = None,
    ) -> RebuildResult | None:
        target_metadata_registry = create_metadata_registry(self._active_metadata_paths(snapshot))
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

    def incremental_rebuild(
        self,
        snapshot: DocumentBuildSnapshot,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        load_cached_document: CachedDocumentLoader | None = None,
        cache_document: CachedDocumentSaver | None = None,
    ) -> RebuildResult | None:
        target_metadata_registry = create_metadata_registry(self._active_metadata_paths(snapshot))
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
    ) -> ManagedDocument:
        parse_result = parser.parse_document(path=uri, text=text)
        facts = extractor.extract(
            parse_result,
            include_lexical_spans=include_lexical_spans,
        )
        return ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            parse_result=parse_result,
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
        total_documents = len(selected_documents)
        for index, document in enumerate(selected_documents, start=1):
            self._raise_if_cancelled()
            analysis_index = analysis_workspace_index(
                root_uri=document.uri,
                documents=documents,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
            )
            analysis = resolver.analyze(
                uri=document.uri,
                facts=document.facts,
                workspace_index=analysis_index,
            )
            documents[document.uri] = replace(document, analysis=analysis)
            self._report_progress(
                f'Analyzing workspace ({index}/{total_documents})',
                _progress_percentage(
                    index=index,
                    total=total_documents,
                    start=start_percentage,
                    end=end_percentage,
                ),
            )

    def _active_metadata_paths(self, snapshot: DocumentBuildSnapshot) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
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

    def extract_facts(facts: DocumentFacts, packages: frozenset[str]) -> DocumentFacts:
        document = documents[facts.uri]
        # Rebuilds with new metadata replace the documents. Within this snapshot,
        # the document's prepared facts can be reused once its packages match.
        if packages == document.facts.required_packages:
            return document.facts
        return extractor.extract(
            document.parse_result,
            include_lexical_spans=document.lexical_spans_included,
            module_rules=facts.module_rules,
            required_packages=packages,
        )

    prepare_dependencies(
        facts_by_uri,
        workspace_index=workspace_index,
        load_facts=load_facts,
        extract_facts=extract_facts,
        metadata_registry=extractor.metadata_registry,
        check_cancelled=check_cancelled,
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
