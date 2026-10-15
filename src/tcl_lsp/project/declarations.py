from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import RLock

from tcl_lsp.cache import register_cache_clearer
from tcl_lsp.common import Span
from tcl_lsp.parser import BracedWord, Command, Parser, ParseResult, word_static_text
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.paths import FileRevision, revision_is_current


@dataclass(frozen=True, slots=True)
class ModuleScope:
    name: str


@dataclass(frozen=True, slots=True)
class DeclarationBlock:
    path: Path
    module: ModuleScope | None
    commands: tuple[Command, ...]


@dataclass(frozen=True, slots=True)
class DeclarationGroup:
    """Declarations and includes in source order."""

    entries: tuple[DeclarationBlock | DeclarationGroup, ...]
    errors: tuple[DeclarationError, ...] = ()
    include_site: tuple[Path, Span] | None = None

    def blocks(self) -> Iterator[DeclarationBlock]:
        for block, _ in self.located_blocks():
            yield block

    def located_blocks(
        self, include_site: tuple[Path, Span] | None = None
    ) -> Iterator[tuple[DeclarationBlock, tuple[Path, Span] | None]]:
        """Keep the entry-file include site beside each declaration's own location."""
        include_site = include_site or self.include_site
        for entry in self.entries:
            if isinstance(entry, DeclarationBlock):
                yield entry, include_site
            else:
                yield from entry.located_blocks(include_site)

    def failures(self) -> Iterator[DeclarationError]:
        yield from self.errors
        for entry in self.entries:
            if isinstance(entry, DeclarationGroup):
                yield from entry.failures()


class DeclarationError(RuntimeError):
    def __init__(self, path: Path, span: Span, message: str) -> None:
        self.path = path
        self.span = span
        super().__init__(message)


@dataclass(frozen=True, slots=True, eq=False)
class DeclarationSnapshot:
    declarations: DeclarationGroup
    revision: FileRevision

    def is_current(self) -> bool:
        return revision_is_current(self.revision)


@dataclass(frozen=True, slots=True)
class EvaluatedDeclarations:
    path: Path
    # The registration result identifies metadata; its execution context does not.
    context: ConfigContext = field(compare=False)
    snapshot: DeclarationSnapshot

    @property
    def name(self) -> str:
        return self.path.name


type MetadataPath = Path | EvaluatedDeclarations


_SNAPSHOTS: OrderedDict[Path, DeclarationSnapshot] = OrderedDict()
_SNAPSHOT_LOCK = RLock()


def _clear_snapshots() -> None:
    with _SNAPSHOT_LOCK:
        _SNAPSHOTS.clear()


register_cache_clearer('metadata', _clear_snapshots)


def load_declaration_snapshot(path: MetadataPath) -> DeclarationSnapshot:
    if isinstance(path, EvaluatedDeclarations):
        return path.snapshot
    path = path.resolve(strict=False)
    with _SNAPSHOT_LOCK:
        snapshot = _SNAPSHOTS.get(path)
        if snapshot is not None and snapshot.is_current():
            _SNAPSHOTS.move_to_end(path)
            return snapshot
        # Record every file read, including transitive source includes. Do not
        # cache failures: a missing include can be created after this request.
        revision: dict[Path, tuple[int, int]] = {}
        parsed = _read_file(path, revision)
        group = _expand(parsed, path, None, (), revision=revision)
        snapshot = DeclarationSnapshot(
            group, tuple((file, mtime, size) for file, (mtime, size) in revision.items())
        )
        _SNAPSHOTS[path] = snapshot
        _SNAPSHOTS.move_to_end(path)
        while len(_SNAPSHOTS) > 256:
            _SNAPSHOTS.popitem(last=False)
        return snapshot


def load_declarations(path: MetadataPath) -> DeclarationGroup:
    return load_declaration_snapshot(path).declarations


def read_declarations(
    parse_result: ParseResult, *, path: Path, recover: bool = False
) -> DeclarationGroup:
    return _expand(parse_result, path.resolve(strict=False), None, (), recover=recover)


def is_declaration_file(path: Path | None) -> bool:
    return path is not None and (path.name == 'tcllsrc.tcl' or path.name.endswith('.meta.tcl'))


def _read_file(path: Path, revision: dict[Path, tuple[int, int]]) -> ParseResult:
    stat = path.stat()
    revision[path] = (stat.st_mtime_ns, stat.st_size)
    return Parser().parse_document(path.as_uri(), path.read_text(encoding='utf-8'))


def _expand(
    parsed: ParseResult,
    path: Path,
    module: ModuleScope | None,
    stack: tuple[Path, ...],
    *,
    recover: bool = False,
    revision: dict[Path, tuple[int, int]] | None = None,
) -> DeclarationGroup:
    if revision is None:
        revision = {}
    if path not in stack:
        stack = (*stack, path)
    if parsed.diagnostics:
        diagnostic = parsed.diagnostics[0]
        raise DeclarationError(path, diagnostic.span, diagnostic.message)
    entries: list[DeclarationBlock | DeclarationGroup] = [DeclarationBlock(path, module, ())]
    commands: list[Command] = []
    errors: list[DeclarationError] = []

    def flush() -> None:
        if commands:
            entries.append(DeclarationBlock(path, module, tuple(commands)))
            commands.clear()

    for command in parsed.script.commands:
        words = tuple(None if word.expanded else word_static_text(word) for word in command.words)
        try:
            if words[:2] == ('meta', 'module'):
                flush()
                scope, body = _module_block(command)
                # Keep empty modules visible to module discovery.
                entries.append(DeclarationBlock(path, scope, ()))
                nested = _module_body(path, body)
                entries.append(
                    _expand(nested, path, scope, stack, recover=recover, revision=revision)
                )
            elif words[0] == 'source':
                flush()
                if len(words) != 2 or not words[1]:
                    raise RuntimeError('`source` requires one static path.')
                target = (path.parent / words[1]).resolve(strict=False)
                included = _include(target, module, stack, revision)
                entries.append(replace(included, include_site=(path, command.span)))
            else:
                commands.append(command)
        except (OSError, RuntimeError) as exc:
            error = (
                exc
                if isinstance(exc, DeclarationError) and exc.path == path
                else DeclarationError(path, command.span, str(exc))
            )
            if not recover:
                if error is exc:
                    raise
                raise error from exc
            errors.append(error)
    flush()
    return DeclarationGroup(tuple(entries), errors=tuple(errors))


def _module_body(path: Path, body: BracedWord) -> ParseResult:
    return Parser().parse_embedded_script(
        path.as_uri(), body.raw_text[1:-1], body.content_span.start
    )


def _module_block(command: Command) -> tuple[ModuleScope, BracedWord]:
    words = command.words
    body = words[-1]
    if len(words) != 4:
        raise RuntimeError('Module declarations must be `meta module name {body}`.')
    name = word_static_text(words[2])
    if any(word.expanded for word in words) or not name or not isinstance(body, BracedWord):
        raise RuntimeError('Module declarations must be `meta module name {body}`.')
    return ModuleScope(name), body


def _include(
    path: Path,
    module: ModuleScope | None,
    stack: tuple[Path, ...],
    revision: dict[Path, tuple[int, int]],
) -> DeclarationGroup:
    if path in stack:
        chain = ' -> '.join(str(item) for item in (*stack, path))
        raise RuntimeError(f'Metadata include cycle: {chain}')
    return _expand(_read_file(path, revision), path, module, stack, revision=revision)


def metadata_root(path: MetadataPath) -> MetadataPath:
    if isinstance(path, EvaluatedDeclarations):
        return path
    resolved = path.expanduser().resolve(strict=False)
    if (
        not resolved.is_dir()
        and resolved.name != 'tcllsrc.tcl'
        and not resolved.name.endswith('.meta.tcl')
        and resolved.suffix in {'.tcl', '.tm'}
    ):
        return resolved.parent
    return resolved


def metadata_roots(path: MetadataPath) -> tuple[MetadataPath, ...]:
    if isinstance(path, EvaluatedDeclarations):
        return (path,)
    if path.is_dir():
        return tuple(root for root, _ in _directory_roots(path))
    return (path,) if path.is_file() else ()


def _directory_roots(directory: Path) -> tuple[tuple[Path, DeclarationGroup], ...]:
    candidates: list[tuple[Path, DeclarationGroup]] = []
    included: set[Path] = set()
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for filename in sorted(filenames):
            if not filename.endswith('.meta.tcl'):
                continue
            path = (Path(root) / filename).resolve(strict=False)
            group = load_declarations(path)
            included.update(block.path for block in group.blocks() if block.path != path)
            candidates.append((path, group))
    return tuple((path, group) for path, group in candidates if path not in included)
