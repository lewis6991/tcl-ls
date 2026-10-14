from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Literal

from tcl_lsp.common import Diagnostic, DiagnosticSeverity, Span

type DiagnosticLevel = DiagnosticSeverity | Literal['off', 'default']

DIAGNOSTIC_LEVELS: tuple[DiagnosticLevel, ...] = (
    'error',
    'warning',
    'information',
    'hint',
    'off',
    'default',
)


@dataclass(frozen=True, slots=True)
class DiagnosticRule:
    code: str
    level: DiagnosticLevel
    directory: Path | None = None
    path_pattern: tuple[str, ...] | None = None
    command: Span | None = None
    directive_span: Span | None = None

    def matches_path(self, path: Path | None) -> bool:
        if self.path_pattern is None:
            return True
        if path is None or self.directory is None or not path.is_relative_to(self.directory):
            return False
        return _matches_path(path.relative_to(self.directory).parts, self.path_pattern)


def parse_diagnostic_rule(
    words: tuple[str | None, ...], *, directory: Path | None = None
) -> DiagnosticRule:
    if (
        len(words) not in {2, 4}
        or any(word is None or not word for word in words)
        or (len(words) == 4 and (words[2] != '-path' or directory is None))
    ):
        suffix = ' ?-path pattern?' if directory is not None else ''
        raise RuntimeError(f'Diagnostic rules must be `diagnostic code level{suffix}`.')
    code, level = words[:2]
    assert code is not None and level is not None
    if level not in DIAGNOSTIC_LEVELS:
        raise RuntimeError(
            f'Invalid diagnostic level `{level}`; use error, warning, information, '
            'hint, off, or default.'
        )
    pattern = None
    if len(words) == 4:
        assert words[3] is not None
        path = PurePosixPath(words[3])
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError('Diagnostic paths must be relative and cannot contain `..`.')
        pattern = path.parts
    return DiagnosticRule(code, level, directory, pattern)


def parse_diagnostic_directive(words: tuple[str, ...]) -> DiagnosticRule:
    if len(words) != 3 or words[0] not in {'diagnostic', 'diagnostic-file'}:
        raise RuntimeError(
            'Diagnostic comments must be `# tcl-ls: diagnostic code level` '
            'or `# tcl-ls: diagnostic-file code level`.'
        )
    return parse_diagnostic_rule(words[1:])


def apply_diagnostic_rules(
    diagnostics: Iterable[Diagnostic], rules: tuple[DiagnosticRule, ...], *, path: Path | None
) -> tuple[Diagnostic, ...]:
    # Select each rule once per document. Always apply the chosen level to the
    # original diagnostic, so `default` can restore a previously disabled code.
    matching = tuple(rule for rule in rules if rule.matches_path(path))
    result: list[Diagnostic] = []
    for diagnostic in diagnostics:
        rule = next(
            (
                rule
                for rule in reversed(matching)
                if fnmatchcase(diagnostic.code, rule.code)
                and (
                    rule.command is None
                    or (
                        rule.command.start.offset
                        <= diagnostic.span.start.offset
                        < rule.command.end.offset
                    )
                )
            ),
            None,
        )
        if rule is None or rule.level == 'default':
            result.append(diagnostic)
        elif rule.level != 'off':
            result.append(replace(diagnostic, severity=rule.level))
    return tuple(result)


def _matches_path(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    # Match from the config directory. A matching directory includes its
    # descendants; `**` spans zero or more components, while `*` stays in one.
    positions: set[int] = {0}
    for component in pattern:
        if not positions:
            return False
        if component == '**':
            positions = set(range(min(positions), len(parts) + 1))
        else:
            positions = {
                index + 1
                for index in positions
                if index < len(parts) and fnmatchcase(parts[index], component)
            }
    return bool(positions)
