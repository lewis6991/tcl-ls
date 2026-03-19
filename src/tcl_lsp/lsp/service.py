from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location
from tcl_lsp.lsp.features.hover import hover as hover_at_position
from tcl_lsp.lsp.features.navigation import (
    definition as definition_at_position,
    references as references_at_position,
)
from tcl_lsp.lsp.features.rename import rename as rename_at_position
from tcl_lsp.lsp.semantic_tokens import encode_document_semantic_tokens
from tcl_lsp.lsp.state import (
    IndexingProgressCallback,
    ManagedDocument,
    RenameEdit,
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


class LanguageService:
    __slots__ = (
        '_documents',
        '_extractor',
        '_library_paths_by_uri',
        '_metadata_registry',
        '_open_document_uris',
        '_parser',
        '_plugin_paths_by_uri',
        '_resolver',
        '_scanned_package_roots',
        '_workspace_index',
    )

    def __init__(
        self,
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
            raise ValueError('Extractor metadata registry does not match LanguageService.')
        if (
            resolver_metadata_registry is not None
            and resolver_metadata_registry != resolved_metadata_registry
        ):
            raise ValueError('Resolver metadata registry does not match LanguageService.')

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
        self._documents: dict[str, ManagedDocument] = {}
        self._scanned_package_roots: set[Path] = set()
        self._open_document_uris: set[str] = set()
        self._plugin_paths_by_uri: dict[str, tuple[Path, ...]] = {}
        self._library_paths_by_uri: dict[str, tuple[Path, ...]] = {}

    def open_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),), progress=progress)
        return self.diagnostics(uri)

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),))
        return self.diagnostics(uri)

    def close_document(self, uri: str) -> tuple[Diagnostic, ...]:
        if uri not in self._documents:
            return ()

        self._open_document_uris.discard(uri)
        self._plugin_paths_by_uri.pop(uri, None)
        self._library_paths_by_uri.pop(uri, None)
        self._rebuild_documents()
        return ()

    def diagnostics(self, uri: str) -> tuple[Diagnostic, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def definition(self, uri: str, line: int, character: int) -> tuple[Location, ...]:
        return definition_at_position(
            self._documents,
            workspace_index=self._workspace_index,
            metadata_registry=self._metadata_registry,
            uri=uri,
            line=line,
            character=character,
        )

    def references(
        self,
        uri: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> tuple[Location, ...]:
        return references_at_position(
            self._documents,
            metadata_registry=self._metadata_registry,
            uri=uri,
            line=line,
            character=character,
            include_declaration=include_declaration,
        )

    def rename(
        self,
        uri: str,
        line: int,
        character: int,
        new_name: str,
    ) -> dict[str, tuple[RenameEdit, ...]] | None:
        return rename_at_position(
            self._documents,
            uri=uri,
            line=line,
            character=character,
            new_name=new_name,
        )

    def hover(self, uri: str, line: int, character: int) -> HoverInfo | None:
        return hover_at_position(
            self._documents,
            uri=uri,
            line=line,
            character=character,
        )

    def document_symbols(self, uri: str) -> tuple[DocumentSymbol, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()
        return document.analysis.document_symbols

    def semantic_tokens(self, uri: str) -> tuple[int, ...] | None:
        document = self._documents.get(uri)
        if document is None:
            return None
        return encode_document_semantic_tokens(
            text=document.text,
            facts=document.facts,
            analysis=document.analysis,
        )

    def get_document(self, uri: str) -> ManagedDocument | None:
        return self._documents.get(uri)

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
            self._plugin_paths_by_uri[uri] = self._configured_plugin_paths(uri)
            self._library_paths_by_uri[uri] = self._configured_library_paths(uri)

        self._report_progress(progress, 'Rebuilding workspace index', 10)
        self._rebuild_documents(pending_documents, progress=progress)

    def _index_document(self, uri: str, text: str, version: int) -> None:
        document = self._build_document(uri=uri, text=text, version=version)
        self._store_document(document)

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

    def _store_document(self, document: ManagedDocument) -> None:
        self._documents[document.uri] = document
        self._workspace_index.update(document.uri, document.facts)

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
            self._scan_package_root(resolved_root)

    def _scan_package_root(self, package_root: Path) -> None:
        scan_package_root(
            package_root,
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
            return self._load_document_from_uri(uri, version=0)

        loaded_documents = load_dependency_documents(
            self._documents,
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

    def _load_document_from_uri(self, uri: str, *, version: int) -> ManagedDocument | None:
        path = source_id_to_path(uri)
        if path is None:
            return None

        try:
            text = read_source_file(path)
        except OSError:
            return None

        return self._build_document(uri=uri, text=text, version=version)

    def _recompute_workspace_analyses(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        start_percentage: int = 75,
        end_percentage: int = 95,
    ) -> None:
        documents = list(self._documents.items())
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
            self._documents[uri] = ManagedDocument(
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
        for uri in self._reachable_analysis_uris(root_uri):
            document = self._documents.get(uri)
            if document is None:
                continue
            workspace_index.update(uri, document.facts)
        return workspace_index

    def _reachable_analysis_uris(self, root_uri: str) -> tuple[str, ...]:
        return reachable_document_uris(
            root_uri,
            documents_by_uri=self._documents,
            workspace_index=self._workspace_index,
            describe_document=managed_document_details,
            metadata_registry=self._metadata_registry,
        )

    def _configured_plugin_paths(self, uri: str) -> tuple[Path, ...]:
        path = source_id_to_path(uri)
        if path is None:
            return ()
        return configured_plugin_paths(path)

    def _configured_library_paths(self, uri: str) -> tuple[Path, ...]:
        path = source_id_to_path(uri)
        if path is None:
            return ()
        return configured_library_paths(path)

    def _active_plugin_paths(self) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in self._open_document_uris:
            for plugin_path in self._plugin_paths_by_uri.get(uri, ()):
                active_paths.setdefault(plugin_path, None)
        return tuple(active_paths)

    def _active_library_paths(self) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in self._open_document_uris:
            for library_path in self._library_paths_by_uri.get(uri, ()):
                active_paths.setdefault(library_path, None)
        return tuple(active_paths)

    def _rebuild_documents(
        self,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> None:
        snapshots: dict[str, tuple[str, int]] = {}
        for uri in self._open_document_uris:
            document = self._documents.get(uri)
            if document is None:
                continue
            snapshots[uri] = (document.text, document.version)
        for uri, text, version in pending_documents:
            snapshots[uri] = (text, version)

        self._set_metadata_registry(create_metadata_registry(self._active_plugin_paths()))
        self._documents = {}
        self._workspace_index = WorkspaceIndex()
        self._scanned_package_roots = set()

        total_snapshots = len(snapshots)
        for index, (uri, (text, version)) in enumerate(snapshots.items(), start=1):
            self._index_document(uri=uri, text=text, version=version)
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

    def _set_metadata_registry(self, metadata_registry: MetadataRegistry) -> None:
        if metadata_registry == self._metadata_registry:
            return

        self._extractor.close()
        self._metadata_registry = metadata_registry
        self._extractor = FactExtractor(self._parser, metadata_registry=metadata_registry)
        self._resolver = Resolver(metadata_registry=metadata_registry)


def _progress_percentage(*, index: int, total: int, start: int, end: int) -> int:
    if total <= 0 or start >= end:
        return end
    completed = (index * (end - start)) // total
    return min(end, start + completed)
