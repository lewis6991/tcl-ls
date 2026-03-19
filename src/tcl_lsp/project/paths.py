from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_SOURCE_PATTERNS = ('*.tcl', '*.tm', '*.test')


def discover_tcl_sources(
    path: Path,
    patterns: tuple[str, ...] = DEFAULT_SOURCE_PATTERNS,
) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    if not path.is_dir():
        return ()
    return tuple(sorted({candidate for pattern in patterns for candidate in path.rglob(pattern)}))


def candidate_package_roots(path: Path) -> tuple[Path, ...]:
    start_directory = path if path.is_dir() else path.parent
    direct_package_root: Path | None = None

    for directory in (start_directory, *start_directory.parents):
        if _has_pkgindex_children(directory):
            return (directory,)
        if direct_package_root is None and (directory / 'pkgIndex.tcl').is_file():
            direct_package_root = directory

    if direct_package_root is None:
        return ()
    return (direct_package_root,)


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
