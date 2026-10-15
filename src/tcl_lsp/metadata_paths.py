from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.declarations import (
    EvaluatedDeclarations,
    MetadataPath,
    load_declaration_snapshot,
    metadata_root,
    metadata_roots,
)
from tcl_lsp.project.paths import FileRevision, file_revision

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

    extra_metadata_paths: tuple[MetadataPath, ...] = ()
    revision: MetadataRevision = ()

    def metadata_paths(self) -> tuple[MetadataPath, ...]:
        return (bundled_metadata_dir(), *self.extra_metadata_paths)

    def metadata_files(self) -> tuple[MetadataPath, ...]:
        files: dict[MetadataPath, None] = {}
        for metadata_path in self.metadata_paths():
            for candidate in _metadata_candidates(metadata_path, self.revision):
                files.setdefault(candidate, None)
        return tuple(files)

    def metadata_file_layers(self) -> tuple[tuple[MetadataPath, tuple[MetadataPath, ...]], ...]:
        layers: list[tuple[MetadataPath, tuple[MetadataPath, ...]]] = []
        seen_files: dict[MetadataPath, None] = {}
        for metadata_path in self.metadata_paths():
            layer_files: list[MetadataPath] = []
            for candidate in _metadata_candidates(metadata_path, self.revision):
                if candidate in seen_files:
                    continue
                seen_files[candidate] = None
                layer_files.append(candidate)
            if layer_files:
                layers.append((metadata_path, tuple(layer_files)))
        return tuple(layers)


@dataclass(frozen=True, slots=True)
class MetadataRegistry:
    catalog: MetadataCatalog = MetadataCatalog()
    modules: tuple[str, ...] = ()
    configuration_roots: tuple[Path, ...] = ()
    context: ConfigContext | None = None

    def with_modules(self, modules: tuple[str, ...]) -> MetadataRegistry:
        return self if modules == self.modules else replace(self, modules=modules)

    def context_for(self, path: Path) -> ConfigContext | None:
        from tcl_lsp.project.config import config_context

        if self.context is not None:
            return self.context
        roots = self.configuration_roots or tuple(
            dict.fromkeys(
                entry.context.workspace_root
                for entry in self.catalog.extra_metadata_paths
                if isinstance(entry, EvaluatedDeclarations)
            )
        )
        matching = [root for root in roots if path.is_relative_to(root)]
        if matching:
            root = max(matching, key=lambda root: len(root.parts))
        elif len(roots) == 1:
            # External dependencies retain the importing workspace's context.
            root = roots[0]
        else:
            return None
        return config_context(path, workspace_root=root)

    def for_source(self, source_id: str) -> MetadataRegistry:
        from tcl_lsp.project.paths import source_id_to_path

        path = source_id_to_path(source_id)
        if path is None:
            return self
        path = path.resolve(strict=False)
        if not self.configuration_roots:
            return self
        if not any(path.is_relative_to(root) for root in self.configuration_roots):
            # Dependencies outside the workspace inherit its configured metadata.
            return replace(self, configuration_roots=(), context=self.context_for(path))
        context = self.context_for(path)
        assert context is not None
        return _registry_for_context(self, path, context)


DEFAULT_METADATA_REGISTRY = MetadataRegistry()


def create_metadata_registry(
    paths: Iterable[MetadataPath | str] = (),
    *,
    module: str | None = None,
    configuration_roots: tuple[Path, ...] = (),
) -> MetadataRegistry:
    from tcl_lsp.analysis.metadata_commands import (
        MetadataPlugin,
        MetadataProcedure,
        metadata_file_summary,
    )

    normalized = _normalize_metadata_paths(paths)
    roots = tuple(path for root in normalized for path in metadata_roots(root))
    revision = dict.fromkeys(
        entry for path in roots for entry in load_declaration_snapshot(path).revision
    )
    # Plugin scripts affect extracted facts even when their metadata is unchanged.
    scripts: list[Path] = []
    for path in roots:
        for command in metadata_file_summary(path, revision=tuple(revision)).commands:
            for annotation in command.annotations:
                if isinstance(annotation, MetadataPlugin):
                    scripts.append(annotation.script_path)
                elif isinstance(annotation, MetadataProcedure):
                    if annotation.parameter_plugin is not None:
                        scripts.append(annotation.parameter_plugin.script_path)
    revision.update(dict.fromkeys(file_revision(scripts)))
    return MetadataRegistry(
        catalog=MetadataCatalog(normalized, tuple(revision)),
        modules=(module,) if module and module != 'Tcl' else (),
        configuration_roots=configuration_roots,
    )


def _registry_for_context(
    registry: MetadataRegistry, path: Path, context: ConfigContext
) -> MetadataRegistry:
    from tcl_lsp.project.config import configured_metadata_paths

    extra = tuple(path for path in registry.catalog.extra_metadata_paths if isinstance(path, Path))
    paths = (*configured_metadata_paths(path, context=context), *extra)
    return _scoped_registry(paths, registry.modules, context, registry.catalog.revision)


@metadata_lru_cache(maxsize=256)
def _scoped_registry(
    paths: tuple[MetadataPath, ...],
    modules: tuple[str, ...],
    context: ConfigContext | None,
    _revision: MetadataRevision,
) -> MetadataRegistry:
    return replace(create_metadata_registry(paths), modules=modules, context=context)


def _normalize_metadata_paths(paths: Iterable[MetadataPath | str]) -> tuple[MetadataPath, ...]:
    return tuple(
        dict.fromkeys(
            metadata_root(path if isinstance(path, EvaluatedDeclarations) else Path(path))
            for path in paths
        )
    )


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
def _metadata_candidates(
    metadata_path: MetadataPath, _revision: MetadataRevision
) -> tuple[MetadataPath, ...]:
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
