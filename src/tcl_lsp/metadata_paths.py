from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.project.declarations import (
    load_declaration_snapshot,
    metadata_root,
    metadata_roots,
)
from tcl_lsp.project.paths import FileRevision

_PACKAGE_META_DIR = Path(__file__).resolve().parent / 'meta'
_REPO_META_DIR = Path(__file__).resolve().parents[2] / 'meta'
METADATA_FILE_SUFFIX = '.meta.tcl'
type MetadataRevision = FileRevision

_SOURCE_FILE_SUFFIXES = ('.tcl', '.tm')


def bundled_metadata_dir() -> Path:
    if _REPO_META_DIR.is_dir():
        return _REPO_META_DIR
    return _PACKAGE_META_DIR


@dataclass(frozen=True, slots=True)
class MetadataCatalog:
    """Metadata files and their revision, independent of module selection."""

    extra_metadata_paths: tuple[Path, ...] = ()
    revision: MetadataRevision = ()

    def metadata_paths(self) -> tuple[Path, ...]:
        return (bundled_metadata_dir(), *self.extra_metadata_paths)

    def metadata_files(self) -> tuple[Path, ...]:
        files: dict[Path, None] = {}
        for metadata_path in self.metadata_paths():
            for candidate in _metadata_candidates(metadata_path, self.revision):
                files.setdefault(candidate, None)
        return tuple(files)

    def metadata_file_layers(self) -> tuple[tuple[Path, tuple[Path, ...]], ...]:
        layers: list[tuple[Path, tuple[Path, ...]]] = []
        seen_files: dict[Path, None] = {}
        for metadata_path in self.metadata_paths():
            layer_files: list[Path] = []
            for candidate in _metadata_candidates(metadata_path, self.revision):
                if candidate in seen_files:
                    continue
                seen_files[candidate] = None
                layer_files.append(candidate)
            if layer_files:
                layers.append((metadata_path.resolve(strict=False), tuple(layer_files)))
        return tuple(layers)


@dataclass(frozen=True, slots=True)
class MetadataRegistry:
    catalog: MetadataCatalog = MetadataCatalog()
    modules: tuple[str, ...] = ()

    def with_modules(self, modules: tuple[str, ...]) -> MetadataRegistry:
        return self if modules == self.modules else replace(self, modules=modules)


DEFAULT_METADATA_REGISTRY = MetadataRegistry()


def create_metadata_registry(
    paths: Iterable[Path | str] = (), *, module: str | None = None
) -> MetadataRegistry:
    normalized = _normalize_metadata_paths(paths)
    revision = dict.fromkeys(
        entry
        for root in normalized
        for path in metadata_roots(root)
        for entry in load_declaration_snapshot(path).revision
    )
    return MetadataRegistry(
        catalog=MetadataCatalog(normalized, tuple(revision)),
        modules=(module,) if module and module != 'Tcl' else (),
    )


def _normalize_metadata_paths(paths: Iterable[Path | str]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(metadata_root(Path(path)) for path in paths))


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


@metadata_lru_cache(maxsize=128)
def _metadata_candidates(metadata_path: Path, _revision: MetadataRevision) -> tuple[Path, ...]:
    return metadata_roots(metadata_path)


def _existing_source_names_for_metadata(path: Path) -> tuple[str, ...]:
    if not _is_metadata_file(path):
        return (path.name,)
    stem = path.name[: -len(METADATA_FILE_SUFFIX)]
    return tuple(
        candidate.name
        for suffix in _SOURCE_FILE_SUFFIXES
        if (candidate := path.with_name(f'{stem}{suffix}')).is_file()
    )
