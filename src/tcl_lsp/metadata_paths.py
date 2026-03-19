from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_META_DIR = Path(__file__).resolve().parent / 'meta'
_REPO_META_DIR = Path(__file__).resolve().parents[2] / 'meta'
METADATA_FILE_SUFFIX = '.meta.tcl'


def bundled_metadata_dir() -> Path:
    if _REPO_META_DIR.is_dir():
        return _REPO_META_DIR
    return _PACKAGE_META_DIR


@dataclass(frozen=True, slots=True)
class MetadataRegistry:
    extra_metadata_paths: tuple[Path, ...] = ()

    def metadata_paths(self) -> tuple[Path, ...]:
        return (bundled_metadata_dir(), *self.extra_metadata_paths)

    def metadata_files(self) -> tuple[Path, ...]:
        files: dict[Path, None] = {}
        for metadata_path in self.metadata_paths():
            if metadata_path.is_dir():
                for candidate in sorted(metadata_path.rglob(f'*{METADATA_FILE_SUFFIX}')):
                    files.setdefault(candidate.resolve(strict=False), None)
                continue

            if metadata_path.is_file() and _is_metadata_file(metadata_path):
                files.setdefault(metadata_path.resolve(strict=False), None)
        return tuple(files)


DEFAULT_METADATA_REGISTRY = MetadataRegistry()


def create_metadata_registry(paths: Iterable[Path | str] = ()) -> MetadataRegistry:
    return MetadataRegistry(extra_metadata_paths=_normalize_metadata_paths(paths))


def _normalize_metadata_paths(paths: Iterable[Path | str]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(_normalize_metadata_path(Path(path)) for path in paths))


def _normalize_metadata_path(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if resolved.is_dir():
        return resolved
    if _is_metadata_file(resolved):
        return resolved
    if resolved.suffix in {'.tcl', '.tm'}:
        return resolved.parent
    return resolved


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
