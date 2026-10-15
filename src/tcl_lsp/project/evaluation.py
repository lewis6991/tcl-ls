from __future__ import annotations

import base64
import os
import shutil
import subprocess
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

from tcl_lsp.cache import metadata_lru_cache, register_cache_clearer
from tcl_lsp.common import Position, Span
from tcl_lsp.parser import BracedWord, Command, Parser, ParseResult, word_static_text
from tcl_lsp.parser.model import Word
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.declarations import (
    DeclarationBlock,
    DeclarationError,
    DeclarationGroup,
    DeclarationSnapshot,
    EvaluatedDeclarations,
    ModuleScope,
)
from tcl_lsp.project.paths import FileRevision, file_revision

type _Events = tuple[tuple[str, ...], ...]

_CACHE: OrderedDict[
    tuple[Path, ConfigContext, tuple[tuple[str, str], ...]], EvaluatedDeclarations
] = OrderedDict()
_LOCK = RLock()


def _clear() -> None:
    with _LOCK:
        _CACHE.clear()


register_cache_clearer('metadata', _clear)


def evaluate_config(
    path: Path, context: ConfigContext, *, buffer: ParseResult | None = None
) -> EvaluatedDeclarations:
    path = path.resolve(strict=False)
    key = (path, context, tuple(sorted(os.environ.items())))
    with _LOCK:
        cached = _CACHE.get(key) if buffer is None else None
        if cached is not None and cached.snapshot.is_current():
            _CACHE.move_to_end(key)
            return cached
        result, volatile = _evaluate(path, context, buffer=buffer)
        if buffer is None and not volatile and not tuple(result.snapshot.declarations.failures()):
            _CACHE[key] = result
            _CACHE.move_to_end(key)
            while len(_CACHE) > 256:
                _CACHE.popitem(last=False)
        return result


def _evaluate(
    path: Path, context: ConfigContext, *, buffer: ParseResult | None
) -> tuple[EvaluatedDeclarations, bool]:
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        raise RuntimeError('The `tclsh` executable is required to evaluate Tcl rc files.')
    from tcl_lsp.metadata_paths import bundled_metadata_dir

    with TemporaryDirectory(prefix='tcl-ls-rc-') as directory:
        output = Path(directory) / 'registrations'
        arguments = [
            tclsh,
            str(bundled_metadata_dir() / 'config/host.tcl'),
            str(output),
            str(path),
            str(context.workspace_root),
            '1' if buffer is not None else '0',
            _buffer_text(buffer) if buffer is not None else '',
        ]
        try:
            process = subprocess.run(
                arguments,
                cwd=next(
                    directory
                    for directory in (context.workspace_root, *context.workspace_root.parents)
                    if directory.is_dir()
                ),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Tcl rc file `{path}` timed out after 5s.') from exc
        if process.returncode or not output.is_file():
            raise RuntimeError(f'Cannot evaluate Tcl rc file `{path}`: {process.stderr.strip()}')
        events = tuple(
            tuple(base64.b64decode(value).decode('utf-8') for value in line.split(':'))
            for line in output.read_text().splitlines()
        )
        if not events or events[-1] != ('done',):
            raise RuntimeError(f'Tcl rc file `{path}` exited before evaluation completed.')

    if buffer is None:
        dependencies: dict[Path, None] = {path: None}
        for event in events:
            if event[0] in {'enter', 'probe'}:
                dependencies.setdefault(Path(event[1]), None)
        snapshot = _saved_snapshot(path, events, file_revision(dependencies))
        volatile = any(event[0] == 'volatile' for event in events)
    else:
        reader = _RegistrationReader(path, buffer)
        declarations, volatile = reader.read(events)
        snapshot = DeclarationSnapshot(declarations, file_revision(reader.dependencies))
    return EvaluatedDeclarations(path, context, snapshot), volatile


@metadata_lru_cache(maxsize=32)
def _saved_snapshot(path: Path, events: _Events, revision: FileRevision) -> DeclarationSnapshot:
    # Workspaces with identical registrations and source revisions can share
    # their immutable declarations and metadata summaries.
    declarations, _ = _RegistrationReader(path, None).read(events)
    return DeclarationSnapshot(declarations, revision)


def _buffer_text(parsed: ParseResult) -> str:
    characters = [' '] * parsed.script.span.end.offset
    for token in parsed.tokens:
        characters[token.span.start.offset : token.span.end.offset] = token.text
    return ''.join(characters)


class _DeclarationSource:
    """Index source locations once and share syntax across rc evaluations."""

    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.offsets = [0]
        for line in self.lines:
            self.offsets.append(self.offsets[-1] + len(line))
        self._commands: dict[tuple[int, str], Command] = {}

    def command(self, line: int, raw: str) -> Command:
        key = (line, raw)
        command = self._commands.get(key)
        if command is None:
            command = self._parse_command(line, raw)
            self._commands[key] = command
        return command

    def _parse_command(self, line: int, raw: str) -> Command:
        row = max(0, min(line - 1, len(self.lines) - 1))
        start = self.offsets[row]
        offset = self.text.find(raw, start) if raw else -1
        if offset < start:
            offset = start
            raw = self.lines[row].strip() if self.lines else ''
        column = offset - start
        # Include preceding comments for documentation on literal declarations.
        comment_start = row
        while comment_start and self.lines[comment_start - 1].lstrip().startswith('#'):
            comment_start -= 1
        prefix = ''.join(self.lines[comment_start:row])
        if prefix:
            position = Position(self.offsets[comment_start], comment_start, 0)
            raw = prefix + ' ' * column + raw
        else:
            position = Position(offset, row, column)
        parsed = Parser().parse_embedded_script(self.path.as_uri(), raw, position)
        if parsed.script.commands:
            return parsed.script.commands[0]
        point = Position(offset, row, column)
        return Command(Span(point, point), ())


@metadata_lru_cache(maxsize=128)
def _declaration_source(path: Path, _mtime_ns: int, _size: int) -> _DeclarationSource:
    return _DeclarationSource(path, path.read_text(encoding='utf-8'))


class _RegistrationReader:
    def __init__(self, path: Path, buffer: ParseResult | None) -> None:
        self.dependencies: dict[Path, None] = {path: None}
        self._sources: dict[Path, _DeclarationSource] = {}
        if buffer is not None:
            self._sources[path] = _DeclarationSource(path, _buffer_text(buffer))
        self._include_sites: dict[Path, tuple[Path, Span]] = {}

    def _command(self, path: Path, line: str, raw: str) -> Command:
        source = self._sources.get(path)
        if source is None:
            _, stamp, size = file_revision((path,))[0]
            source = _declaration_source(path, stamp, size)
            self._sources[path] = source
        return source.command(int(line), raw)

    def read(self, events: _Events) -> tuple[DeclarationGroup, bool]:
        entries: list[DeclarationBlock | DeclarationGroup] = []
        stack: list[tuple[list[DeclarationBlock | DeclarationGroup], tuple[Path, Span] | None]] = []
        errors: list[DeclarationError] = []
        volatile = False
        for kind, *values in events:
            if kind == 'probe':
                self.dependencies.setdefault(Path(values[0]), None)
            elif kind == 'volatile':
                volatile = True
            elif kind == 'enter':
                target, module, caller, line, raw = values
                self.dependencies.setdefault(Path(target), None)
                site = None
                if caller:
                    site = (Path(caller), self._command(Path(caller), line, raw).span)
                    self._include_sites[Path(target)] = self._include_sites.get(Path(caller), site)
                stack.append((entries, site))
                entries = [
                    DeclarationBlock(Path(target), ModuleScope(module) if module else None, ())
                ]
            elif kind == 'leave':
                parent, site = stack.pop()
                parent.append(DeclarationGroup(tuple(entries), include_site=site))
                entries = parent
            elif kind == 'scope':
                path, module = values
                entries.append(
                    DeclarationBlock(Path(path), ModuleScope(module) if module else None, ())
                )
            elif kind == 'command':
                path, line, raw, module, *words = values
                location = Path(path)
                command = self._command(location, line, raw)
                evaluated: list[Word] = []
                for index, value in enumerate(words):
                    original = command.words[index] if index < len(command.words) else None
                    if (
                        original is not None
                        and not original.expanded
                        and word_static_text(original) == value
                    ):
                        evaluated.append(original)
                    else:
                        span = original.span if original is not None else command.span
                        evaluated.append(BracedWord(span, span, value, '{' + value + '}'))
                command = replace(command, words=tuple(evaluated))
                scope = ModuleScope(module) if module else None
                if (
                    entries
                    and isinstance(entries[-1], DeclarationBlock)
                    and entries[-1].path == location
                    and entries[-1].module == scope
                ):
                    previous = entries[-1]
                    assert isinstance(previous, DeclarationBlock)
                    entries[-1] = replace(previous, commands=(*previous.commands, command))
                else:
                    entries.append(DeclarationBlock(location, scope, (command,)))
            elif kind == 'error':
                path, line, message = values
                location = Path(path)
                site = self._include_sites.get(location)
                if site is not None:
                    location, span = site
                else:
                    span = self._command(location, line, '').span
                errors.append(DeclarationError(location, span, message))
        return DeclarationGroup(tuple(entries), errors=tuple(errors)), volatile
