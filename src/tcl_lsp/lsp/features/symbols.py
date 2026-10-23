from __future__ import annotations

from collections.abc import Iterable, Mapping

from tcl_lsp.analysis.builtins import builtin_definition_targets, registry_for_packages
from tcl_lsp.analysis.facts.utils import name_tail
from tcl_lsp.analysis.model import CommandImport, DefinitionTarget
from tcl_lsp.analysis.modules import registry_at_offset
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry


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
    # Only the first binding becomes a definition. Later writes identify the
    # same variable without being reads of its value.
    direct_matches.extend(
        binding.symbol_id
        for binding in document.facts.variable_bindings
        if binding.uri == uri and binding.span.contains(line=line, character=character)
    )
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


def reference_command_names(
    document: ManagedDocument, *, line: int, character: int
) -> frozenset[str] | None:
    """Limit command resolution only when the selected symbol is a command."""
    definitions = [
        definition
        for definition in document.analysis.definitions
        if definition.location.uri == document.uri
        and definition.span.contains(line=line, character=character)
    ]
    if definitions:
        if any(definition.kind != 'function' for definition in definitions):
            return None
        return frozenset(name_tail(definition.name) for definition in definitions)

    references = [
        resolution.reference
        for resolution in document.analysis.resolutions
        if resolution.reference.span.contains(line=line, character=character)
    ]
    if not references or any(
        reference.kind != 'command' or reference.name is None for reference in references
    ):
        return None
    return frozenset(
        name_tail(reference.name) for reference in references if reference.name is not None
    )


def definitions_for_command_import(
    documents: Iterable[ManagedDocument],
    *,
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
            metadata_registry = registry_for_packages(
                metadata_registry, document.facts.required_packages
            )
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
