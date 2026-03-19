from __future__ import annotations

import time
from pathlib import Path
from typing import TextIO

from tcl_lsp.common import Diagnostic

from .model import CheckReport, ProjectDiagnostic

_TAB_SIZE = 4


class Palette:
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


class StreamReporter:
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
        palette: Palette,
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
        self._update_status(f'Preparing 0/{source_count} workspaces', force=True)

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
            f'{display_path(path, self._root)} ({self._background_sources} total)',
        )

    def workspace_started(self, current: int, total: int, root: Path, source_count: int) -> None:
        source_label = 'file' if source_count == 1 else 'files'
        self._update_status(
            f'Preparing workspace {current}/{total}: '
            f'{display_path(root, self._root)} ({source_count} {source_label})',
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


def format_report(
    report: CheckReport,
    *,
    color: bool = False,
    context_lines: int = 0,
) -> str:
    palette = Palette(color)
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
    palette: Palette,
    context_lines: int,
) -> str:
    lines: list[str] = []
    groups = group_diagnostics(report.diagnostics)
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
    palette: Palette,
    context_lines: int,
) -> str:
    count_label = 'diagnostic' if len(diagnostics) == 1 else 'diagnostics'
    header = f'{palette.file(str(display_path(path, root)))}{palette.dim(f" ({len(diagnostics)} {count_label})")}'

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


def format_summary(report: CheckReport, *, palette: Palette) -> str:
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
            f'  {palette.code(code.ljust(code_width))} '
            f'{palette.count(str(counts[code]).rjust(count_width))}'
        )

    return '\n'.join(lines)


def group_diagnostics(
    diagnostics: tuple[ProjectDiagnostic, ...],
) -> tuple[tuple[Path, tuple[ProjectDiagnostic, ...]], ...]:
    groups: dict[Path, list[ProjectDiagnostic]] = {}
    for diagnostic in diagnostics:
        groups.setdefault(diagnostic.path, []).append(diagnostic)
    return tuple((path, tuple(group)) for path, group in groups.items())


def display_path(path: Path, root: Path) -> Path:
    if root.is_file():
        return Path(path.name) if path.name else path
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _format_context_lines(
    source_lines: list[str],
    diagnostic: Diagnostic,
    *,
    line_number_width: int,
    palette: Palette,
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
    palette: Palette,
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


def _format_duration(seconds: float) -> str:
    if seconds >= 60:
        minutes = int(seconds // 60)
        remaining_seconds = seconds - (minutes * 60)
        return f'{minutes}m {remaining_seconds:04.1f}s'
    if seconds >= 1:
        return f'{seconds:.1f}s'
    return f'{int(seconds * 1000)}ms'


def _severity_color(severity: str) -> str:
    return {
        'error': '31',
        'warning': '33',
        'information': '36',
        'hint': '35',
    }.get(severity, '37')
