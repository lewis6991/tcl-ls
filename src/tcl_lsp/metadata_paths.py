from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.cache import metadata_lru_cache

_PACKAGE_META_DIR = Path(__file__).resolve().parent / 'meta'
_REPO_META_DIR = Path(__file__).resolve().parents[2] / 'meta'
METADATA_FILE_SUFFIX = '.meta.tcl'
_SOURCE_FILE_SUFFIXES = ('.tcl', '.tm')


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
            for candidate in _metadata_candidates(metadata_path):
                files.setdefault(candidate, None)
        return tuple(files)

    def metadata_file_layers(self) -> tuple[tuple[Path, tuple[Path, ...]], ...]:
        layers: list[tuple[Path, tuple[Path, ...]]] = []
        seen_files: dict[Path, None] = {}
        for metadata_path in self.metadata_paths():
            layer_files: list[Path] = []
            for candidate in _metadata_candidates(metadata_path):
                if candidate in seen_files:
                    continue
                seen_files[candidate] = None
                layer_files.append(candidate)
            if layer_files:
                layers.append((metadata_path.resolve(strict=False), tuple(layer_files)))
        return tuple(layers)


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
    names: dict[str, None] = {path.name: None}
    source_names = _existing_source_names_for_metadata(path)
    if len(source_names) <= 1:
        for source_name in source_names or (source_name_for_metadata(path),):
            names.setdefault(source_name, None)
    return tuple(names)


def source_name_for_metadata(path: Path) -> str:
    source_names = _existing_source_names_for_metadata(path)
    if len(source_names) == 1:
        return source_names[0]
    if not _is_metadata_file(path):
        return path.name
    stem = path.name[: -len(METADATA_FILE_SUFFIX)]
    return f'{stem}.tcl'


@metadata_lru_cache(maxsize=None)
def _metadata_candidates(metadata_path: Path) -> tuple[Path, ...]:
    if metadata_path.is_dir():
        return tuple(
            candidate.resolve(strict=False)
            for candidate in sorted(metadata_path.rglob(f'*{METADATA_FILE_SUFFIX}'))
        )
    if metadata_path.is_file() and _is_metadata_file(metadata_path):
        return (metadata_path.resolve(strict=False),)
    return ()


def _existing_source_names_for_metadata(path: Path) -> tuple[str, ...]:
    if not _is_metadata_file(path):
        return (path.name,)
    stem = path.name[: -len(METADATA_FILE_SUFFIX)]
    return tuple(
        candidate.name
        for suffix in _SOURCE_FILE_SUFFIXES
        if (candidate := path.with_name(f'{stem}{suffix}')).is_file()
    )
