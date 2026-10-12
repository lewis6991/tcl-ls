from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Span
from tcl_lsp.parser import BracedWord, Command, Parser, ParseResult, word_static_text


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


def load_declarations(path: Path) -> DeclarationGroup:
    path = path.resolve(strict=False)
    return read_declarations(_read_file(path), path=path)


def read_declarations(
    parse_result: ParseResult, *, path: Path, recover: bool = False
) -> DeclarationGroup:
    return _expand(parse_result, path.resolve(strict=False), None, (), recover=recover)


def is_declaration_file(path: Path | None) -> bool:
    return path is not None and (path.name == 'tcllsrc.tcl' or path.name.endswith('.meta.tcl'))


def _read_file(path: Path) -> ParseResult:
    stat = path.stat()
    return _parse_file(path, stat.st_mtime_ns, stat.st_size)


@metadata_lru_cache(maxsize=256)
def _parse_file(path: Path, _mtime: int, _size: int) -> ParseResult:
    return Parser().parse_document(path.as_uri(), path.read_text(encoding='utf-8'))


def _expand(
    parsed: ParseResult,
    path: Path,
    module: ModuleScope | None,
    stack: tuple[Path, ...],
    *,
    recover: bool = False,
) -> DeclarationGroup:
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
                entries.append(_expand(nested, path, scope, stack, recover=recover))
            elif words[0] == 'source':
                flush()
                if len(words) != 2 or not words[1]:
                    raise RuntimeError('`source` requires one static path.')
                target = (path.parent / words[1]).resolve(strict=False)
                included = _include(target, module, stack)
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


@metadata_lru_cache(maxsize=256)
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


def _include(path: Path, module: ModuleScope | None, stack: tuple[Path, ...]) -> DeclarationGroup:
    if path in stack:
        chain = ' -> '.join(str(item) for item in (*stack, path))
        raise RuntimeError(f'Metadata include cycle: {chain}')
    return _expand(_read_file(path), path, module, stack)


def metadata_root(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if (
        not resolved.is_dir()
        and resolved.name != 'tcllsrc.tcl'
        and not resolved.name.endswith('.meta.tcl')
        and resolved.suffix in {'.tcl', '.tm'}
    ):
        return resolved.parent
    return resolved


def metadata_roots(path: Path) -> tuple[Path, ...]:
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
            group = _include(path, None, ())
            included.update(block.path for block in group.blocks() if block.path != path)
            candidates.append((path, group))
    return tuple((path, group) for path, group in candidates if path not in included)
