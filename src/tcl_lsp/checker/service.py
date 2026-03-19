from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import (
    DocumentFacts,
    FactExtractor,
    Resolver,
    WorkspaceIndex,
)
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.common import Diagnostic
from tcl_lsp.metadata_paths import MetadataRegistry, create_metadata_registry
from tcl_lsp.parser import Parser
from tcl_lsp.project.config import configured_library_paths, configured_plugin_paths
from tcl_lsp.project.indexing import (
    PackageIndexCatalog,
    apply_package_index_catalog,
    build_package_index_catalog,
    load_dependency_documents,
)
from tcl_lsp.project.paths import (
    discover_tcl_sources,
    read_source_file,
    source_id_to_path,
)

from .model import CheckReport, ProjectDiagnostic
from .reporting import StreamReporter

DEFAULT_WORKER_COUNT = 8
_worker_document_cache: _DocumentCache | None = None
_worker_resolver: Resolver | None = None
_worker_package_index_catalog: PackageIndexCatalog = ()


@dataclass(frozen=True, slots=True)
class _ProjectDocument:
    path: Path
    uri: str
    text: str
    facts: DocumentFacts


@dataclass(frozen=True, slots=True)
class _AnalysisUnit:
    root: Path
    source_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _PreparedUnit:
    unit: _AnalysisUnit
    source_documents: tuple[_ProjectDocument, ...]
    background_source_paths: tuple[Path, ...]
    workspace_index: WorkspaceIndex


@dataclass(frozen=True, slots=True)
class _UnitSourceReport:
    path: Path
    text: str
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class _UnitAnalysisReport:
    source_reports: tuple[_UnitSourceReport, ...]
    background_source_paths: tuple[Path, ...]


class _DocumentCache:
    __slots__ = ('_documents', '_extractor', '_parser')

    def __init__(self, *, parser: Parser, extractor: FactExtractor) -> None:
        self._parser = parser
        self._extractor = extractor
        self._documents: dict[Path, _ProjectDocument] = {}

    @property
    def metadata_registry(self) -> MetadataRegistry:
        return self._extractor.metadata_registry

    def get(self, path: Path) -> _ProjectDocument:
        resolved_path = path.resolve(strict=False)
        document = self._documents.get(resolved_path)
        if document is not None:
            return document

        document = _index_document(
            resolved_path,
            parser=self._parser,
            extractor=self._extractor,
        )
        self._documents[resolved_path] = document
        return document


def check_project(
    path: Path,
    *,
    threads: int = DEFAULT_WORKER_COUNT,
    plugin_paths: Sequence[Path | str] = (),
    reporter: StreamReporter | None = None,
) -> CheckReport:
    return _run_check(
        path,
        reporter=reporter,
        threads=threads,
        plugin_paths=plugin_paths,
    )


def _run_check(
    path: Path,
    reporter: StreamReporter | None = None,
    *,
    threads: int = 1,
    plugin_paths: Sequence[Path | str] = (),
) -> CheckReport:
    target = path.expanduser().resolve(strict=False)
    active_plugin_paths = (*configured_plugin_paths(target), *plugin_paths)
    active_library_paths = configured_library_paths(target)
    metadata_registry = create_metadata_registry(active_plugin_paths)
    worker_count = _worker_count(threads)
    started = time.monotonic()
    units = _discover_analysis_units(target)
    if not units:
        raise ValueError(f'No Tcl sources found under {path.expanduser()}')

    parser = Parser()
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    package_index_catalog = build_package_index_catalog(
        target,
        parser=parser,
        extractor=extractor,
        library_paths=active_library_paths,
    )

    source_count = sum(len(unit.source_paths) for unit in units)
    source_text_by_path: dict[Path, str] = {}
    diagnostics: list[ProjectDiagnostic] = []
    background_source_paths: set[Path] = set()
    analyzed_sources = 0
    analysis_started = False

    if reporter is not None:
        reporter.start_indexing(len(units))

    parent_document_cache = _DocumentCache(parser=parser, extractor=extractor)
    parent_resolver = Resolver(metadata_registry=metadata_registry)
    executor = _create_unit_executor(
        worker_count,
        package_index_catalog,
        active_plugin_paths,
    )
    executor_context = executor if executor is not None else nullcontext(None)
    with executor_context as executor:
        futures = (
            [executor.submit(_analyze_unit_worker, unit) for unit in units]
            if executor is not None
            else None
        )

        for unit_index, unit in enumerate(units, start=1):
            if reporter is not None:
                reporter.workspace_started(
                    unit_index,
                    len(units),
                    unit.root,
                    len(unit.source_paths),
                )

            if futures is None:
                unit_report = _analyze_unit(
                    unit,
                    document_cache=parent_document_cache,
                    resolver=parent_resolver,
                    package_index_catalog=package_index_catalog,
                )
            else:
                unit_report = futures[unit_index - 1].result()

            for background_path in unit_report.background_source_paths:
                if background_path in background_source_paths:
                    continue
                background_source_paths.add(background_path)
                if reporter is not None:
                    reporter.background_source_loaded(background_path)

            if reporter is not None:
                reporter.source_indexed(unit_index, len(units))
                if not analysis_started:
                    reporter.start_analysis(source_count)
                    analysis_started = True

            for source_report in unit_report.source_reports:
                source_text_by_path[source_report.path] = source_report.text
                diagnostics.extend(
                    ProjectDiagnostic(path=source_report.path, diagnostic=diagnostic)
                    for diagnostic in source_report.diagnostics
                )
                analyzed_sources += 1
                if reporter is not None:
                    reporter.source_analyzed(
                        current=analyzed_sources,
                        total=source_count,
                        path=source_report.path,
                        text=source_report.text,
                        diagnostics=source_report.diagnostics,
                    )

    report = CheckReport(
        root=target,
        source_count=source_count,
        background_source_count=len(background_source_paths),
        diagnostics=tuple(diagnostics),
        source_text_by_path=source_text_by_path,
        elapsed_seconds=time.monotonic() - started,
    )
    if reporter is not None:
        reporter.finish(report)
    return report


def _prepare_unit(
    unit: _AnalysisUnit,
    *,
    document_cache: _DocumentCache,
    package_index_catalog: PackageIndexCatalog,
) -> _PreparedUnit:
    workspace_index = WorkspaceIndex()
    apply_package_index_catalog(workspace_index, package_index_catalog)
    documents_by_uri: dict[str, _ProjectDocument] = {}
    source_documents: list[_ProjectDocument] = []
    for source_path in unit.source_paths:
        document = document_cache.get(source_path)
        documents_by_uri[document.uri] = document
        source_documents.append(document)
        workspace_index.update(document.uri, document.facts)

    def load_document(uri: str) -> _ProjectDocument | None:
        source_path = source_id_to_path(uri)
        if source_path is None:
            return None
        try:
            return document_cache.get(source_path)
        except OSError:
            return None

    background_documents = load_dependency_documents(
        documents_by_uri,
        workspace_index=workspace_index,
        describe_document=_project_document_details,
        load_document=load_document,
        metadata_registry=document_cache.metadata_registry,
    )
    background_source_paths = tuple(sorted(document.path for document in background_documents))
    return _PreparedUnit(
        unit=unit,
        source_documents=tuple(source_documents),
        background_source_paths=background_source_paths,
        workspace_index=workspace_index,
    )


def _prepare_source_workspace(
    document: _ProjectDocument,
    *,
    package_index_catalog: PackageIndexCatalog,
    document_cache: _DocumentCache,
) -> tuple[WorkspaceIndex, tuple[Path, ...]]:
    workspace_index = WorkspaceIndex()
    apply_package_index_catalog(workspace_index, package_index_catalog)
    documents_by_uri = {document.uri: document}
    workspace_index.update(document.uri, document.facts)

    def load_document(uri: str) -> _ProjectDocument | None:
        source_path = source_id_to_path(uri)
        if source_path is None:
            return None
        try:
            return document_cache.get(source_path)
        except OSError:
            return None

    background_documents = load_dependency_documents(
        documents_by_uri,
        workspace_index=workspace_index,
        describe_document=_project_document_details,
        load_document=load_document,
        metadata_registry=document_cache.metadata_registry,
    )
    background_source_paths = tuple(sorted(document.path for document in background_documents))
    return workspace_index, background_source_paths


def _discover_analysis_units(target: Path) -> tuple[_AnalysisUnit, ...]:
    if target.is_file():
        resolved_target = target.resolve(strict=False)
        package_root = _nearest_package_workspace_root(resolved_target)
        if package_root is not None:
            source_paths = tuple(
                path.resolve(strict=False) for path in discover_tcl_sources(package_root)
            )
            unit_root = package_root
        else:
            source_paths = (resolved_target,)
            unit_root = resolved_target
        return (_AnalysisUnit(root=unit_root, source_paths=source_paths),)

    workspace_roots = _workspace_roots_under(target)
    if workspace_roots:
        return tuple(
            _AnalysisUnit(
                root=workspace_root,
                source_paths=tuple(
                    path.resolve(strict=False) for path in discover_tcl_sources(workspace_root)
                ),
            )
            for workspace_root in workspace_roots
        )

    source_paths = tuple(path.resolve(strict=False) for path in discover_tcl_sources(target))
    units_by_root: dict[Path, list[Path]] = {}
    for source_path in source_paths:
        unit_root = _analysis_unit_root(source_path, target)
        units_by_root.setdefault(unit_root, []).append(source_path)

    return tuple(
        _AnalysisUnit(root=root, source_paths=tuple(sorted(paths)))
        for root, paths in sorted(units_by_root.items(), key=lambda item: str(item[0]))
    )


def _analysis_unit_root(source_path: Path, target_root: Path) -> Path:
    package_root = _nearest_package_workspace_root(source_path)
    if package_root is not None:
        return package_root

    if source_path.parent == target_root:
        return target_root
    return source_path.parent


def _nearest_package_workspace_root(source_path: Path) -> Path | None:
    for directory in (source_path.parent, *source_path.parent.parents):
        if (directory / 'pkgIndex.tcl').is_file():
            return directory
    return None


def _workspace_roots_under(target: Path) -> tuple[Path, ...]:
    if not target.is_dir():
        return ()
    return tuple(
        sorted(
            {
                pkg_index_path.parent.resolve(strict=False)
                for pkg_index_path in target.rglob('pkgIndex.tcl')
            }
        )
    )


def _is_package_unit(unit: _AnalysisUnit) -> bool:
    return unit.root.is_dir() and (unit.root / 'pkgIndex.tcl').is_file()


def _index_document(path: Path, *, parser: Parser, extractor: FactExtractor) -> _ProjectDocument:
    text = read_source_file(path)
    uri = path.as_uri()
    parse_result = parser.parse_document(path=uri, text=text)
    return _ProjectDocument(
        path=path,
        uri=uri,
        text=text,
        facts=extractor.extract(parse_result, include_parse_result=False),
    )


def _project_document_details(document: _ProjectDocument) -> tuple[str, Path | None, DocumentFacts]:
    return (document.uri, document.path, document.facts)


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[int, int, str, str]:
    start = diagnostic.span.start
    return (start.line, start.character, diagnostic.code, diagnostic.message)


def _worker_count(value: str | int) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError('value must be >= 1')
    return parsed


def _analyze_unit(
    unit: _AnalysisUnit,
    *,
    document_cache: _DocumentCache,
    resolver: Resolver,
    package_index_catalog: PackageIndexCatalog,
) -> _UnitAnalysisReport:
    if _is_package_unit(unit):
        return _analyze_package_unit(
            unit,
            document_cache=document_cache,
            resolver=resolver,
            package_index_catalog=package_index_catalog,
        )

    prepared_unit = _prepare_unit(
        unit,
        document_cache=document_cache,
        package_index_catalog=package_index_catalog,
    )
    source_reports = tuple(
        _analyze_source_document(
            document,
            resolver=resolver,
            workspace_index=prepared_unit.workspace_index,
        )
        for document in prepared_unit.source_documents
    )
    return _UnitAnalysisReport(
        source_reports=source_reports,
        background_source_paths=prepared_unit.background_source_paths,
    )


def _analyze_package_unit(
    unit: _AnalysisUnit,
    *,
    document_cache: _DocumentCache,
    resolver: Resolver,
    package_index_catalog: PackageIndexCatalog,
) -> _UnitAnalysisReport:
    source_reports: list[_UnitSourceReport] = []
    background_source_paths: set[Path] = set()

    for source_path in unit.source_paths:
        document = document_cache.get(source_path)
        workspace_index, loaded_background_paths = _prepare_source_workspace(
            document,
            package_index_catalog=package_index_catalog,
            document_cache=document_cache,
        )
        background_source_paths.update(loaded_background_paths)
        source_reports.append(
            _analyze_source_document(
                document,
                resolver=resolver,
                workspace_index=workspace_index,
            )
        )

    return _UnitAnalysisReport(
        source_reports=tuple(source_reports),
        background_source_paths=tuple(sorted(background_source_paths)),
    )


def _analyze_source_document(
    document: _ProjectDocument,
    *,
    resolver: Resolver,
    workspace_index: WorkspaceIndex,
) -> _UnitSourceReport:
    required_packages = dependency_required_packages(
        document.path,
        document.facts,
        workspace_index,
        metadata_registry=resolver.metadata_registry,
    )
    diagnostics = tuple(
        sorted(
            resolver.analyze(
                uri=document.uri,
                facts=document.facts,
                workspace_index=workspace_index,
                additional_required_packages=required_packages,
            ).diagnostics,
            key=_diagnostic_key,
        )
    )
    return _UnitSourceReport(
        path=document.path,
        text=document.text,
        diagnostics=diagnostics,
    )


def _initialize_unit_worker(
    package_index_catalog: PackageIndexCatalog,
    plugin_paths: tuple[str, ...],
) -> None:
    global _worker_document_cache, _worker_package_index_catalog, _worker_resolver
    metadata_registry = create_metadata_registry(plugin_paths)
    parser = Parser()
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    _worker_document_cache = _DocumentCache(parser=parser, extractor=extractor)
    _worker_resolver = Resolver(metadata_registry=metadata_registry)
    _worker_package_index_catalog = package_index_catalog


def _analyze_unit_worker(unit: _AnalysisUnit) -> _UnitAnalysisReport:
    document_cache, resolver, package_index_catalog = _worker_services()
    return _analyze_unit(
        unit,
        document_cache=document_cache,
        resolver=resolver,
        package_index_catalog=package_index_catalog,
    )


def _worker_services() -> tuple[
    _DocumentCache,
    Resolver,
    PackageIndexCatalog,
]:
    global _worker_document_cache, _worker_package_index_catalog, _worker_resolver
    if _worker_document_cache is None or _worker_resolver is None:
        _initialize_unit_worker((), ())
    assert _worker_document_cache is not None
    assert _worker_resolver is not None
    return (_worker_document_cache, _worker_resolver, _worker_package_index_catalog)


def _create_unit_executor(
    worker_count: int,
    package_index_catalog: PackageIndexCatalog,
    plugin_paths: Sequence[Path | str],
) -> ProcessPoolExecutor | None:
    if worker_count <= 1:
        return None
    try:
        return ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_unit_worker,
            initargs=(
                package_index_catalog,
                tuple(str(path) for path in plugin_paths),
            ),
        )
    except NotImplementedError:
        return None
    except PermissionError:
        return None
    except OSError:
        return None
