from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.lsp.state import (
    IndexingProgressCallback,
    ManagedDocument,
    empty_analysis,
    managed_document_details,
)
from tcl_lsp.metadata_paths import MetadataRegistry, create_metadata_registry
from tcl_lsp.parser import Parser
from tcl_lsp.project.indexing import (
    load_dependency_documents,
    reachable_document_uris,
    scan_package_root,
)
from tcl_lsp.project.paths import candidate_package_roots, read_source_file, source_id_to_path

type CancelCallback = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class DocumentBuildSnapshot:
    documents: dict[str, ManagedDocument]
    open_document_uris: tuple[str, ...]
    plugin_paths_by_uri: dict[str, tuple[Path, ...]]
    library_paths_by_uri: dict[str, tuple[Path, ...]]


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
    ) -> RebuildResult | None:
        target_metadata_registry = create_metadata_registry(self._active_plugin_paths(snapshot))
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
                    parser=parser,
                    extractor=extractor,
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
                metadata_registry=target_metadata_registry,
                start_percentage=50,
                end_percentage=75,
            )
            self._recompute_workspace_analyses(
                documents,
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
    ) -> ManagedDocument:
        parse_result = parser.parse_document(path=uri, text=text)
        facts = extractor.extract(parse_result)
        return ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            parse_result=parse_result,
            facts=facts,
            analysis=empty_analysis(uri, facts.document_symbols),
        )

    def _discover_package_roots(
        self,
        *,
        uri: str,
        parser: Parser,
        extractor: FactExtractor,
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
            scan_package_root(
                resolved_root,
                parser=parser,
                extractor=extractor,
                workspace_index=workspace_index,
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
        metadata_registry: MetadataRegistry,
        start_percentage: int,
        end_percentage: int,
    ) -> None:
        def load_document(uri: str) -> ManagedDocument | None:
            self._raise_if_cancelled()

            path = source_id_to_path(uri)
            if path is None:
                return None

            try:
                text = read_source_file(path)
            except OSError:
                return None

            return self._build_document(
                parser=parser,
                extractor=extractor,
                uri=uri,
                text=text,
                version=0,
            )

        def on_document_loaded(document: ManagedDocument) -> None:
            self._discover_package_roots(
                uri=document.uri,
                parser=parser,
                extractor=extractor,
                workspace_index=workspace_index,
                scanned_package_roots=scanned_package_roots,
                library_paths_by_uri=library_paths_by_uri,
            )

        loaded_documents = load_dependency_documents(
            documents,
            workspace_index=workspace_index,
            describe_document=managed_document_details,
            load_document=load_document,
            metadata_registry=metadata_registry,
            on_document_loaded=on_document_loaded,
        )

        loaded_background_documents = 0
        for _ in loaded_documents:
            self._raise_if_cancelled()
            loaded_background_documents += 1
            self._report_progress(
                f'Loading workspace dependencies ({loaded_background_documents})',
                min(end_percentage, start_percentage + loaded_background_documents),
            )

    def _recompute_workspace_analyses(
        self,
        documents: dict[str, ManagedDocument],
        *,
        resolver: Resolver,
        workspace_index: WorkspaceIndex,
        metadata_registry: MetadataRegistry,
        start_percentage: int,
        end_percentage: int,
    ) -> None:
        document_items = list(documents.items())
        total_documents = len(document_items)
        for index, (uri, document) in enumerate(document_items, start=1):
            self._raise_if_cancelled()
            analysis_workspace_index = self._analysis_workspace_index(
                root_uri=uri,
                documents=documents,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
            )
            source_path = source_id_to_path(uri)
            additional_required_packages: frozenset[str]
            if source_path is None:
                additional_required_packages = frozenset()
            else:
                additional_required_packages = dependency_required_packages(
                    source_path,
                    document.facts,
                    analysis_workspace_index,
                    metadata_registry=metadata_registry,
                )
            analysis = resolver.analyze(
                uri=uri,
                facts=document.facts,
                workspace_index=analysis_workspace_index,
                additional_required_packages=additional_required_packages,
            )
            documents[uri] = ManagedDocument(
                uri=document.uri,
                version=document.version,
                text=document.text,
                parse_result=document.parse_result,
                facts=document.facts,
                analysis=analysis,
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

    def _analysis_workspace_index(
        self,
        *,
        root_uri: str,
        documents: dict[str, ManagedDocument],
        workspace_index: WorkspaceIndex,
        metadata_registry: MetadataRegistry,
    ) -> WorkspaceIndex:
        analysis_workspace_index = WorkspaceIndex()
        for pkg_index_uri, entries in workspace_index.package_indexes():
            analysis_workspace_index.update_package_index(pkg_index_uri, entries)
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
            analysis_workspace_index.update(uri, document.facts)
        return analysis_workspace_index

    def _active_plugin_paths(self, snapshot: DocumentBuildSnapshot) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in snapshot.open_document_uris:
            for plugin_path in snapshot.plugin_paths_by_uri.get(uri, ()):
                active_paths.setdefault(plugin_path, None)
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
