from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from tcl_lsp.cache import clear_cache_group

_PACKAGE_META_DIR = Path(__file__).resolve().parent / 'meta'
_REPO_META_DIR = Path(__file__).resolve().parents[2] / 'meta'
METADATA_FILE_SUFFIX = '.meta.tcl'
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
            for candidate in sorted(metadata_path.rglob(f'*{METADATA_FILE_SUFFIX}')):
                files.setdefault(candidate.resolve(strict=False), None)
            continue

        if metadata_path.is_file() and _is_metadata_file(metadata_path):
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
    if _is_metadata_file(resolved):
        return resolved
    if resolved.suffix in {'.tcl', '.tm'}:
        return resolved.parent
    return resolved


def _clear_metadata_caches() -> None:
    clear_cache_group('metadata')


def _is_metadata_file(path: Path) -> bool:
    return path.name.endswith(METADATA_FILE_SUFFIX)


def metadata_lookup_names(path: Path) -> tuple[str, ...]:
    source_name = source_name_for_metadata(path)
    if source_name == path.name:
        return (path.name,)
    return (path.name, source_name)


def source_name_for_metadata(path: Path) -> str:
    if not _is_metadata_file(path):
        return path.name
    stem = path.name[: -len(METADATA_FILE_SUFFIX)]
    return f'{stem}.tcl'
