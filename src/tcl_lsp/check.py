from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from tcl_lsp.analysis import (
    DocumentFacts,
    FactExtractor,
    PackageIndexEntry,
    Resolver,
    WorkspaceIndex,
)
from tcl_lsp.analysis.metadata_effects import (
    dependency_required_packages,
    metadata_dependency_overlay,
)
from tcl_lsp.common import Diagnostic
from tcl_lsp.metadata_paths import configure_metadata_paths, metadata_paths_context
from tcl_lsp.parser import Parser
from tcl_lsp.project_config import configured_library_paths, configured_plugin_paths
from tcl_lsp.workspace import (
    candidate_package_roots,
    discover_tcl_sources,
    read_source_file,
    source_id_to_path,
)

type ColorMode = Literal['auto', 'always', 'never']

_TAB_SIZE = 4
_DEFAULT_WORKER_COUNT = 8
_worker_document_cache: _DocumentCache | None = None
_worker_resolver: Resolver | None = None
_worker_package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectDiagnostic:
    path: Path
    diagnostic: Diagnostic


@dataclass(frozen=True, slots=True)
class CheckReport:
    root: Path
    source_count: int
    background_source_count: int
    diagnostics: tuple[ProjectDiagnostic, ...]
    source_text_by_path: dict[Path, str]
    elapsed_seconds: float

    @property
    def files_with_diagnostics(self) -> int:
        return len({item.path for item in self.diagnostics})

    @property
    def diagnostic_counts(self) -> Counter[str]:
        return Counter(item.diagnostic.code for item in self.diagnostics)


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


class _Palette:
    __slots__ = ('enabled',)

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def bold(self, text: str) -> str:
        return self._style(text, '1')

    def dim(self, text: str) -> str:
        return self._style(text, '2')

    def heading(self, text: str) -> str:
        return self._style(text, '1', '36')

    def file(self, text: str) -> str:
        return self._style(text, '1', '34')

    def code(self, text: str) -> str:
        return self._style(text, '35')

    def count(self, text: str) -> str:
        return self._style(text, '1')

    def caret(self, text: str, severity: str) -> str:
        return self._style(text, _severity_color(severity))

    def severity(self, text: str, severity: str) -> str:
        return self._style(text, '1', _severity_color(severity))

    def _style(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return f'\x1b[{";".join(codes)}m{text}\x1b[0m'


class _StreamReporter:
    __slots__ = (
        '_background_sources',
        '_context_lines',
        '_diagnostics_seen',
        '_err',
        '_last_status_update',
        '_out',
        '_palette',
        '_progress_enabled',
        '_rendered_files',
        '_root',
        '_status_visible',
    )

    def __init__(
        self,
        *,
        root: Path,
        out: TextIO,
        err: TextIO,
        palette: _Palette,
        context_lines: int,
    ) -> None:
        self._root = root
        self._out = out
        self._err = err
        self._palette = palette
        self._context_lines = context_lines
        self._progress_enabled = err.isatty()
        self._last_status_update = 0.0
        self._status_visible = False
        self._rendered_files = 0
        self._background_sources = 0
        self._diagnostics_seen = 0

    def start_indexing(self, source_count: int) -> None:
        self._update_status(
            f'Preparing 0/{source_count} workspaces',
            force=True,
        )

    def source_indexed(self, current: int, total: int) -> None:
        background_suffix = (
            f', loaded {self._background_sources} background sources'
            if self._background_sources
            else ''
        )
        self._update_status(
            f'Prepared {current}/{total} workspaces{background_suffix}',
            force=current == total,
        )

    def background_source_loaded(self, path: Path) -> None:
        self._background_sources += 1
        self._update_status(
            'Loaded background source '
            f'{_display_path(path, self._root)} ({self._background_sources} total)',
        )

    def workspace_started(self, current: int, total: int, root: Path, source_count: int) -> None:
        source_label = 'file' if source_count == 1 else 'files'
        self._update_status(
            f'Preparing workspace {current}/{total}: '
            f'{_display_path(root, self._root)} ({source_count} {source_label})',
            force=True,
        )

    def start_analysis(self, source_count: int) -> None:
        self._diagnostics_seen = 0
        self._update_status(
            f'Analyzing 0/{source_count} source files, 0 diagnostics',
            force=True,
        )

    def source_analyzed(
        self,
        *,
        current: int,
        total: int,
        path: Path,
        text: str,
        diagnostics: tuple[Diagnostic, ...],
    ) -> None:
        if diagnostics:
            self._clear_status()
            if self._rendered_files:
                print(file=self._out)
            print(
                format_file_diagnostics(
                    path=path,
                    text=text,
                    diagnostics=diagnostics,
                    root=self._root,
                    palette=self._palette,
                    context_lines=self._context_lines,
                ),
                file=self._out,
                flush=True,
            )
            self._rendered_files += 1

        self._diagnostics_seen += len(diagnostics)
        self._update_status(
            f'Analyzing {current}/{total} source files, {self._diagnostics_seen} diagnostics',
            force=current == total,
        )

    def finish(self, report: CheckReport) -> None:
        self._clear_status()
        if self._rendered_files:
            print(file=self._out)
        print(format_summary(report, palette=self._palette), file=self._out)

    def abort(self) -> None:
        self._clear_status()

    def _update_status(self, message: str, *, force: bool = False) -> None:
        if not self._progress_enabled:
            return

        now = time.monotonic()
        if not force and now - self._last_status_update < 0.1:
            return

        self._last_status_update = now
        print(f'\r\x1b[2K{self._palette.dim(message)}', end='', file=self._err, flush=True)
        self._status_visible = True

    def _clear_status(self) -> None:
        if not self._progress_enabled or not self._status_visible:
            return
        print('\r\x1b[2K', end='', file=self._err, flush=True)
        self._status_visible = False


def check_project(
    path: Path,
    *,
    threads: int = _DEFAULT_WORKER_COUNT,
    plugin_paths: Sequence[Path | str] = (),
) -> CheckReport:
    return _run_check(path, threads=threads, plugin_paths=plugin_paths)


def format_report(
    report: CheckReport,
    *,
    color: bool = False,
    context_lines: int = 0,
) -> str:
    palette = _Palette(color)
    sections: list[str] = []
    diagnostics_output = format_diagnostics(
        report,
        palette=palette,
        context_lines=context_lines,
    )
    if diagnostics_output:
        sections.append(diagnostics_output)
    sections.append(format_summary(report, palette=palette))
    return '\n\n'.join(sections)


def format_diagnostics(
    report: CheckReport,
    *,
    palette: _Palette,
    context_lines: int,
) -> str:
    lines: list[str] = []
    groups = _group_diagnostics(report.diagnostics)
    for index, (path, diagnostics) in enumerate(groups):
        if index:
            lines.append('')
        text = report.source_text_by_path.get(path)
        if text is None:
            continue
        lines.append(
            format_file_diagnostics(
                path=path,
                text=text,
                diagnostics=tuple(diagnostic.diagnostic for diagnostic in diagnostics),
                root=report.root,
                palette=palette,
                context_lines=context_lines,
            )
        )
    return '\n'.join(lines)


def format_file_diagnostics(
    *,
    path: Path,
    text: str,
    diagnostics: tuple[Diagnostic, ...],
    root: Path,
    palette: _Palette,
    context_lines: int,
) -> str:
    count_label = 'diagnostic' if len(diagnostics) == 1 else 'diagnostics'
    display_path = _display_path(path, root)
    header = (
        f'{palette.file(str(display_path))}{palette.dim(f" ({len(diagnostics)} {count_label})")}'
    )

    location_width = max(
        len(f'{diagnostic.span.start.line + 1}:{diagnostic.span.start.character + 1}')
        for diagnostic in diagnostics
    )
    severity_width = max(len(diagnostic.severity) for diagnostic in diagnostics)
    code_width = max(len(diagnostic.code) for diagnostic in diagnostics)

    lines = [header]
    source_lines = text.splitlines()
    line_number_width = _line_number_width(source_lines, diagnostics, context_lines)
    for diagnostic in diagnostics:
        start = diagnostic.span.start
        location = f'{start.line + 1}:{start.character + 1}'.rjust(location_width)
        severity = palette.severity(
            diagnostic.severity.ljust(severity_width),
            diagnostic.severity,
        )
        code = palette.code(diagnostic.code.ljust(code_width))
        lines.append(f'  {palette.dim(location)}  {severity}  {code}  {diagnostic.message}')
        lines.extend(
            _format_context_lines(
                source_lines,
                diagnostic,
                line_number_width=line_number_width,
                palette=palette,
                context_lines=context_lines,
            )
        )

    return '\n'.join(lines)


def format_summary(report: CheckReport, *, palette: _Palette) -> str:
    file_label = 'file' if report.source_count == 1 else 'files'
    lines = [palette.heading('Summary')]
    lines.append(
        f'Scanned {report.source_count} Tcl {file_label} under {report.root} '
        f'in {_format_duration(report.elapsed_seconds)}.'
    )

    if report.background_source_count:
        background_label = 'file' if report.background_source_count == 1 else 'files'
        lines.append(
            f'Loaded {report.background_source_count} background source {background_label} '
            'from package indexes or static source commands.'
        )

    if not report.diagnostics:
        lines.append('No diagnostics found.')
        return '\n'.join(lines)

    diagnostic_label = 'diagnostic' if len(report.diagnostics) == 1 else 'diagnostics'
    affected_file_label = 'file' if report.files_with_diagnostics == 1 else 'files'
    lines.append(
        f'Found {len(report.diagnostics)} {diagnostic_label} in '
        f'{report.files_with_diagnostics} {affected_file_label}.'
    )

    counts = report.diagnostic_counts
    code_width = max(len(code) for code in counts)
    count_width = len(str(max(counts.values())))
    for code in sorted(counts):
        lines.append(
            f'  {palette.code(code.ljust(code_width))} {palette.count(str(counts[code]).rjust(count_width))}'
        )

    return '\n'.join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    target = Path(args.path)
    palette = _Palette(_color_enabled(args.color, sys.stdout))
    reporter = _StreamReporter(
        root=target.expanduser().resolve(strict=False),
        out=sys.stdout,
        err=sys.stderr,
        palette=palette,
        context_lines=args.context_lines,
    )

    try:
        report = _run_check(
            target,
            reporter=reporter,
            threads=args.threads,
            plugin_paths=args.plugin_paths,
        )
    except KeyboardInterrupt:
        reporter.abort()
        print('Interrupted.', file=sys.stderr)
        return 130
    except (OSError, ValueError, AssertionError) as exc:
        reporter.abort()
        print(str(exc), file=sys.stderr)
        return 1

    if args.fail_on_diagnostics and report.diagnostics:
        return 1
    return 0


def _run_check(
    path: Path,
    reporter: _StreamReporter | None = None,
    *,
    threads: int = 1,
    plugin_paths: Sequence[Path | str] = (),
) -> CheckReport:
    target = path.expanduser().resolve(strict=False)
    active_plugin_paths = (*configured_plugin_paths(target), *plugin_paths)
    active_library_paths = configured_library_paths(target)
    with metadata_paths_context(active_plugin_paths):
        worker_count = _worker_count(threads)
        started = time.monotonic()
        units = _discover_analysis_units(target)
        if not units:
            raise ValueError(f'No Tcl sources found under {path.expanduser()}')

        parser = Parser()
        extractor = FactExtractor(parser)
        package_index_catalog = _build_package_index_catalog(
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
        parent_resolver = Resolver()
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
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
) -> _PreparedUnit:
    workspace_index = WorkspaceIndex()
    _apply_package_index_catalog(workspace_index, package_index_catalog)
    documents_by_uri: dict[str, _ProjectDocument] = {}
    source_documents: list[_ProjectDocument] = []
    for source_path in unit.source_paths:
        document = document_cache.get(source_path)
        documents_by_uri[document.uri] = document
        source_documents.append(document)
        workspace_index.update(document.uri, document.facts)
    background_source_paths = _load_background_documents(
        documents_by_uri,
        document_cache=document_cache,
        workspace_index=workspace_index,
    )
    return _PreparedUnit(
        unit=unit,
        source_documents=tuple(source_documents),
        background_source_paths=background_source_paths,
        workspace_index=workspace_index,
    )


def _prepare_source_workspace(
    document: _ProjectDocument,
    *,
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
    document_cache: _DocumentCache,
) -> tuple[WorkspaceIndex, tuple[Path, ...]]:
    workspace_index = WorkspaceIndex()
    _apply_package_index_catalog(workspace_index, package_index_catalog)
    documents_by_uri = {document.uri: document}
    workspace_index.update(document.uri, document.facts)
    background_source_paths = _load_background_documents(
        documents_by_uri,
        document_cache=document_cache,
        workspace_index=workspace_index,
    )
    return workspace_index, background_source_paths


def _load_background_documents(
    documents_by_uri: dict[str, _ProjectDocument],
    *,
    document_cache: _DocumentCache,
    workspace_index: WorkspaceIndex,
) -> tuple[Path, ...]:
    failed_uris: set[str] = set()
    loaded_paths: set[Path] = set()

    while True:
        loaded_document = False
        for document in tuple(documents_by_uri.values()):
            for source_uri in _background_source_uris(document, workspace_index):
                if source_uri in documents_by_uri or source_uri in failed_uris:
                    continue

                source_path = source_id_to_path(source_uri)
                if source_path is None:
                    failed_uris.add(source_uri)
                    continue
                try:
                    background_document = document_cache.get(source_path)
                except OSError:
                    failed_uris.add(source_uri)
                    continue

                documents_by_uri[background_document.uri] = background_document
                workspace_index.update(background_document.uri, background_document.facts)
                loaded_paths.add(background_document.path)
                loaded_document = True
                break
            if loaded_document:
                break
        if not loaded_document:
            return tuple(sorted(loaded_paths))


def _background_source_uris(
    document: _ProjectDocument,
    workspace_index: WorkspaceIndex,
) -> tuple[str, ...]:
    uris: dict[str, None] = {}
    overlay = metadata_dependency_overlay(
        document.path,
        document.facts,
        workspace_index,
    )
    for source_uri in overlay.source_uris:
        uris.setdefault(source_uri, None)
    for package_name in overlay.required_packages:
        for source_uri in workspace_index.package_source_uris(package_name):
            uris.setdefault(source_uri, None)
    return tuple(uris)


def _build_package_index_catalog(
    target: Path,
    *,
    parser: Parser,
    extractor: FactExtractor,
    library_paths: Sequence[Path] = (),
) -> tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...]:
    seen_paths: set[Path] = set()
    catalog_entries: list[tuple[str, tuple[PackageIndexEntry, ...]]] = []
    for root in _package_index_scan_roots(target, library_paths=library_paths):
        for pkg_index_path in sorted(root.rglob('pkgIndex.tcl')):
            resolved_path = pkg_index_path.resolve(strict=False)
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            indexed_entry = _index_package_index(
                resolved_path,
                parser=parser,
                extractor=extractor,
            )
            if indexed_entry is not None:
                catalog_entries.append(indexed_entry)
    return tuple(catalog_entries)


def _apply_package_index_catalog(
    workspace_index: WorkspaceIndex,
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
) -> None:
    for pkg_index_uri, package_index_entries in package_index_catalog:
        workspace_index.update_package_index(pkg_index_uri, package_index_entries)


def _package_index_scan_roots(
    target: Path,
    *,
    library_paths: Sequence[Path] = (),
) -> tuple[Path, ...]:
    roots: dict[Path, None] = {}
    candidate_roots = tuple(candidate_package_roots(target))
    if candidate_roots:
        for package_root in candidate_roots:
            roots.setdefault(package_root.resolve(strict=False), None)
    elif target.is_dir():
        roots.setdefault(target, None)

    for library_path in library_paths:
        roots.setdefault(library_path.resolve(strict=False), None)
    return tuple(roots)


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
        _AnalysisUnit(
            root=root,
            source_paths=tuple(sorted(paths)),
        )
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


def _group_diagnostics(
    diagnostics: tuple[ProjectDiagnostic, ...],
) -> tuple[tuple[Path, tuple[ProjectDiagnostic, ...]], ...]:
    groups: dict[Path, list[ProjectDiagnostic]] = {}
    for diagnostic in diagnostics:
        groups.setdefault(diagnostic.path, []).append(diagnostic)
    return tuple((path, tuple(group)) for path, group in groups.items())


def _format_context_lines(
    source_lines: list[str],
    diagnostic: Diagnostic,
    *,
    line_number_width: int,
    palette: _Palette,
    context_lines: int,
) -> list[str]:
    target_line = diagnostic.span.start.line
    if target_line < 0 or target_line >= len(source_lines):
        return []

    start_line = max(0, target_line - context_lines)
    end_line = min(len(source_lines) - 1, target_line + context_lines)

    rendered: list[str] = []
    for line_number in range(start_line, end_line + 1):
        line_text = source_lines[line_number].expandtabs(_TAB_SIZE)
        gutter = palette.dim(f'    {str(line_number + 1).rjust(line_number_width)} | ')
        rendered.append(f'{gutter}{line_text}')
        if line_number == target_line:
            rendered.append(
                _format_caret_line(
                    source_lines[line_number],
                    diagnostic,
                    line_number_width=line_number_width,
                    palette=palette,
                )
            )
    return rendered


def _format_caret_line(
    source_line: str,
    diagnostic: Diagnostic,
    *,
    line_number_width: int,
    palette: _Palette,
) -> str:
    start_character = min(max(diagnostic.span.start.character, 0), len(source_line))
    if diagnostic.span.end.line == diagnostic.span.start.line:
        end_character = min(max(diagnostic.span.end.character, start_character), len(source_line))
    else:
        end_character = len(source_line)

    start_column = _visual_column(source_line, start_character)
    end_column = _visual_column(source_line, end_character)
    if end_column <= start_column:
        end_column = start_column + 1

    marker = ' ' * start_column + palette.caret(
        '^' * max(1, end_column - start_column),
        diagnostic.severity,
    )
    gutter = palette.dim(f'    {" " * line_number_width} | ')
    return f'{gutter}{marker}'


def _line_number_width(
    source_lines: list[str],
    diagnostics: tuple[Diagnostic, ...],
    context_lines: int,
) -> int:
    highest_line_number = max(
        min(len(source_lines), diagnostic.span.start.line + context_lines + 1)
        for diagnostic in diagnostics
    )
    return len(str(max(1, highest_line_number)))


def _visual_column(text: str, character: int) -> int:
    column = 0
    for char in text[:character]:
        if char == '\t':
            column += _TAB_SIZE - (column % _TAB_SIZE)
        else:
            column += 1
    return column


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='tcl-check',
        description='Analyze Tcl sources under a file or directory and print diagnostics.',
    )
    parser.add_argument('path', help='Tcl source file or project directory to analyze')
    parser.add_argument(
        '--color',
        choices=('auto', 'always', 'never'),
        default='auto',
        help='Colorize output. Defaults to `auto`.',
    )
    parser.add_argument(
        '--context-lines',
        type=_non_negative_int,
        default=0,
        help='Show this many lines of surrounding source context for each diagnostic.',
    )
    parser.add_argument(
        '--fail-on-diagnostics',
        action='store_true',
        help='Exit with status 1 when diagnostics are reported.',
    )
    parser.add_argument(
        '-j',
        '--threads',
        type=_worker_count,
        default=_DEFAULT_WORKER_COUNT,
        help=(
            f'Index documents with this many worker processes. Defaults to {_DEFAULT_WORKER_COUNT}.'
        ),
    )
    parser.add_argument(
        '--plugin-path',
        action='append',
        dest='plugin_paths',
        default=[],
        help=(
            'Load project metadata from this path. Accepts a metadata directory, '
            'a metadata `.meta.tcl` file, or a Tcl plugin `.tcl` file. When a '
            'plugin script is passed, sibling metadata files are discovered from '
            'its parent directory. Legacy `.tm` plugin scripts are also accepted. '
            'Paths from `tcllsrc.tcl` are loaded automatically.'
        ),
    )
    return parser.parse_args(argv)


def _display_path(path: Path, root: Path) -> Path:
    if root.is_file():
        return Path(path.name) if path.name else path
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[int, int, str, str]:
    start = diagnostic.span.start
    return (start.line, start.character, diagnostic.code, diagnostic.message)


def _color_enabled(mode: ColorMode, stream: TextIO) -> bool:
    if mode == 'always':
        return True
    if mode == 'never':
        return False
    return stream.isatty() and 'NO_COLOR' not in os.environ


def _format_duration(seconds: float) -> str:
    if seconds >= 60:
        minutes = int(seconds // 60)
        remaining_seconds = seconds - (minutes * 60)
        return f'{minutes}m {remaining_seconds:04.1f}s'
    if seconds >= 1:
        return f'{seconds:.1f}s'
    return f'{int(seconds * 1000)}ms'


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError('value must be >= 0')
    return parsed


def _worker_count(value: str | int) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('value must be >= 1')
    return parsed


def _analyze_unit(
    unit: _AnalysisUnit,
    *,
    document_cache: _DocumentCache,
    resolver: Resolver,
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
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
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
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
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
    plugin_paths: tuple[str, ...],
) -> None:
    global _worker_document_cache, _worker_package_index_catalog, _worker_resolver
    configure_metadata_paths(plugin_paths)
    parser = Parser()
    extractor = FactExtractor(parser)
    _worker_document_cache = _DocumentCache(parser=parser, extractor=extractor)
    _worker_resolver = Resolver()
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
    tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
]:
    global _worker_document_cache, _worker_package_index_catalog, _worker_resolver
    if _worker_document_cache is None or _worker_resolver is None:
        _initialize_unit_worker((), ())
    assert _worker_document_cache is not None
    assert _worker_resolver is not None
    return (_worker_document_cache, _worker_resolver, _worker_package_index_catalog)


def _index_package_index(
    path: Path,
    *,
    parser: Parser,
    extractor: FactExtractor,
) -> tuple[str, tuple[PackageIndexEntry, ...]] | None:
    try:
        text = read_source_file(path)
    except OSError:
        return None

    pkg_index_uri = path.as_uri()
    parse_result = parser.parse_document(path=pkg_index_uri, text=text)
    facts = extractor.extract(parse_result, include_parse_result=False)
    return (pkg_index_uri, facts.package_index_entries)


def _create_unit_executor(
    worker_count: int,
    package_index_catalog: tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...],
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
    except NotImplementedError, PermissionError, OSError:
        return None


def _severity_color(severity: str) -> str:
    return {
        'error': '31',
        'warning': '33',
        'information': '36',
        'hint': '35',
    }.get(severity, '37')
