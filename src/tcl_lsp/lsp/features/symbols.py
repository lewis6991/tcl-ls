from __future__ import annotations

from collections.abc import Iterable, Mapping

from tcl_lsp.analysis.builtins import builtin_definition_targets
from tcl_lsp.analysis.model import CommandImport, DefinitionTarget
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
    if direct_matches:
        return tuple(dict.fromkeys(direct_matches))

    resolved_matches: list[str] = []
    for resolution in document.analysis.resolutions:
        if resolution.reference.span.contains(line=line, character=character):
            resolved_matches.extend(resolution.target_symbol_ids)
    return tuple(dict.fromkeys(resolved_matches))


def symbol_kind(documents: Iterable[ManagedDocument], symbol_id: str) -> str | None:
    for document in documents:
        for procedure in document.facts.procedures:
            if procedure.symbol_id == symbol_id:
                return 'function'
        for binding in document.facts.variable_bindings:
            if binding.symbol_id == symbol_id:
                return 'variable'
    return None


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
    for definition in builtin_definition_targets(metadata_registry=metadata_registry):
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
