from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from tcl_lsp.cache import clear_cache_group

_PACKAGE_META_DIR = Path(__file__).resolve().parent / 'meta'
_REPO_META_DIR = Path(__file__).resolve().parents[2] / 'meta'
_extra_metadata_paths: tuple[Path, ...] = ()
_METADATA_LOCK = RLock()


def metadata_dir() -> Path:
    if _REPO_META_DIR.is_dir():
        return _REPO_META_DIR
    return _PACKAGE_META_DIR


def metadata_paths() -> tuple[Path, ...]:
    return (metadata_dir(), *_extra_metadata_paths)


def metadata_files() -> tuple[Path, ...]:
    files: dict[Path, None] = {}
    for metadata_path in metadata_paths():
        if metadata_path.is_dir():
            for candidate in sorted(metadata_path.rglob('*.tcl')):
                files.setdefault(candidate.resolve(strict=False), None)
            continue

        if metadata_path.is_file() and metadata_path.suffix == '.tcl':
            files.setdefault(metadata_path.resolve(strict=False), None)
    return tuple(files)


def configure_metadata_paths(paths: Iterable[Path | str]) -> tuple[Path, ...]:
    normalized = tuple(dict.fromkeys(_normalize_metadata_path(Path(path)) for path in paths))
    with _METADATA_LOCK:
        global _extra_metadata_paths
        if normalized == _extra_metadata_paths:
            return _extra_metadata_paths
        _extra_metadata_paths = normalized
        _clear_metadata_caches()
        return _extra_metadata_paths


@contextmanager
def metadata_paths_context(paths: Iterable[Path | str]) -> Iterator[None]:
    with _METADATA_LOCK:
        previous = _extra_metadata_paths
    configure_metadata_paths(paths)
    try:
        yield
    finally:
        configure_metadata_paths(previous)


def _normalize_metadata_path(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if resolved.is_dir():
        return resolved
    if resolved.suffix == '.tm':
        return resolved.parent
    return resolved


def _clear_metadata_caches() -> None:
    clear_cache_group('metadata')
