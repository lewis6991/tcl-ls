from __future__ import annotations

from collections.abc import Iterable, Mapping

from tcl_lsp.analysis.builtins import builtin_definition_targets, registry_for_packages
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.analysis.model import CommandImport, DefinitionTarget
from tcl_lsp.analysis.modules import registry_at_offset
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.project.paths import source_id_to_path


def symbol_ids_at_position(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
) -> tuple[str, ...]:
    document = documents_by_uri.get(uri)
    if document is None:
        return ()

    direct_matches = [
        definition.symbol_id
        for definition in document.analysis.definitions
        if definition.location.uri == uri
        and definition.span.contains(line=line, character=character)
    ]
    if direct_matches:
        return tuple(dict.fromkeys(direct_matches))

    resolved_matches: list[str] = []
    for resolution in document.analysis.resolutions:
        if resolution.reference.span.contains(line=line, character=character):
            resolved_matches.extend(resolution.target_symbol_ids)
    return tuple(dict.fromkeys(resolved_matches))


def symbol_kind(documents: Iterable[ManagedDocument], symbol_id: str) -> str | None:
    for document in documents:
        for definition in document.analysis.definitions:
            if definition.symbol_id == symbol_id:
                return definition.kind
    return None


def definitions_for_command_import(
    documents: Iterable[ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    command_import: CommandImport,
) -> tuple[DefinitionTarget, ...]:
    definitions: list[DefinitionTarget] = []
    seen: set[str] = set()
    target_name = _qualified_command_name(command_import.target_name)

    def add_definition(definition: DefinitionTarget) -> None:
        if definition.kind != 'function':
            return
        if definition.symbol_id in seen:
            return
        seen.add(definition.symbol_id)
        definitions.append(definition)

    for document in documents:
        if document.facts.uri == command_import.uri:
            metadata_registry = registry_at_offset(
                metadata_registry,
                document.facts.module_scopes,
                command_import.span.start.offset,
            )
            source_path = source_id_to_path(document.uri)
            required = (
                dependency_required_packages(
                    source_path,
                    document.facts,
                    workspace_index,
                    metadata_registry=metadata_registry,
                )
                if source_path is not None
                else frozenset(require.name for require in document.facts.package_requires)
            )
            metadata_registry = registry_for_packages(metadata_registry, required)
        for definition in document.analysis.definitions:
            qualified_name = _qualified_command_name(definition.name)
            if command_import.kind == 'exact':
                if qualified_name != target_name:
                    continue
            elif not _is_direct_namespace_member(qualified_name, target_name):
                continue
            add_definition(definition)

    for definition in builtin_definition_targets(metadata_registry=metadata_registry):
        qualified_name = _qualified_command_name(definition.name)
        if command_import.kind == 'exact':
            if qualified_name != target_name:
                continue
        elif not _is_direct_namespace_member(qualified_name, target_name):
            continue
        add_definition(definition)

    return tuple(definitions)


def definitions_for_symbols(
    documents: Iterable[ManagedDocument],
    *,
    metadata_registry: MetadataRegistry,
    symbol_ids: tuple[str, ...],
) -> tuple[DefinitionTarget, ...]:
    definitions: list[DefinitionTarget] = []
    seen: set[str] = set()
    for document in documents:
        for definition in document.analysis.definitions:
            if definition.symbol_id not in symbol_ids or definition.symbol_id in seen:
                continue
            seen.add(definition.symbol_id)
            definitions.append(definition)
    # Resolution has already selected the module at each reference. Lookup
    # by symbol ID must retain those targets even outside the selected scope.
    for definition in builtin_definition_targets(
        metadata_registry=metadata_registry, all_modules=True
    ):
        if definition.symbol_id not in symbol_ids or definition.symbol_id in seen:
            continue
        seen.add(definition.symbol_id)
        definitions.append(definition)
    return tuple(definitions)


def _qualified_command_name(name: str) -> str:
    if name.startswith('::'):
        return name
    return f'::{name}'


def _is_direct_namespace_member(qualified_name: str, namespace: str) -> bool:
    if namespace == '::':
        return qualified_name.startswith('::') and '::' not in qualified_name[2:]

    prefix = namespace + '::'
    if not qualified_name.startswith(prefix):
        return False
    return '::' not in qualified_name[len(prefix) :]
