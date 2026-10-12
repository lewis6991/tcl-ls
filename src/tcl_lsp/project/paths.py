from __future__ import annotations

from collections.abc import Iterable
from os import walk
from os.path import normcase
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_SOURCE_PATTERNS = ('*.tcl', '*.tm', '*.test')
type FileRevision = tuple[tuple[Path, int, int], ...]


def file_revision(paths: Iterable[Path]) -> FileRevision:
    revision: list[tuple[Path, int, int]] = []
    for path in dict.fromkeys(paths):
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = (-1, -1)
        revision.append((path, stamp[0], stamp[1]))
    return tuple(revision)


def revision_is_current(revision: FileRevision) -> bool:
    return file_revision(path for path, _, _ in revision) == revision


def discover_tcl_sources(
    path: Path,
    patterns: tuple[str, ...] = DEFAULT_SOURCE_PATTERNS,
) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    if not path.is_dir():
        return ()
    if patterns == DEFAULT_SOURCE_PATTERNS:
        # Walk once for the common extensions, rather than once per pattern.
        return tuple(
            sorted(
                Path(directory) / name
                for directory, directories, files in walk(path)
                for name in (*directories, *files)
                if normcase(name).endswith(('.tcl', '.tm', '.test'))
            )
        )
    return tuple(sorted({candidate for pattern in patterns for candidate in path.rglob(pattern)}))


def candidate_package_roots(path: Path) -> tuple[Path, ...]:
    start_directory = path if path.is_dir() else path.parent

    for directory in (start_directory, *start_directory.parents):
        if (directory / 'pkgIndex.tcl').is_file():
            return (directory,)
        if _has_pkgindex_children(directory):
            return (directory,)
    return ()


def read_source_file(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ('utf-8', 'iso-8859-1'):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise AssertionError(f'Could not decode {path}: {last_error}')


def source_id_to_path(source_id: str) -> Path | None:
    parsed = urlparse(source_id)
    if parsed.scheme == 'file':
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_id)


def _has_pkgindex_children(directory: Path) -> bool:
    try:
        for child in directory.iterdir():
            if child.is_dir() and (child / 'pkgIndex.tcl').is_file():
                return True
    except OSError:
        return False
    return False


__all__ = [
    'DEFAULT_SOURCE_PATTERNS',
    'candidate_package_roots',
    'discover_tcl_sources',
    'read_source_file',
    'source_id_to_path',
]
