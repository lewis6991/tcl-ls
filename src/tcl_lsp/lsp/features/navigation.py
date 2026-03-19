from __future__ import annotations

from collections.abc import Mapping

from tcl_lsp.analysis import WorkspaceIndex
from tcl_lsp.common import Location
from tcl_lsp.lsp.features.symbols import (
    definitions_for_command_import,
    definitions_for_symbols,
    symbol_ids_at_position,
)
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry


def definition(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    uri: str,
    line: int,
    character: int,
) -> tuple[Location, ...]:
    package_locations = package_definition_locations(
        documents_by_uri,
        workspace_index=workspace_index,
        uri=uri,
        line=line,
        character=character,
    )
    if package_locations:
        return package_locations

    command_import_locations = command_import_definition_locations(
        documents_by_uri,
        metadata_registry=metadata_registry,
        uri=uri,
        line=line,
        character=character,
    )
    if command_import_locations:
        return command_import_locations

    symbol_ids = symbol_ids_at_position(documents_by_uri, uri=uri, line=line, character=character)
    if not symbol_ids:
        return ()
    definitions = definitions_for_symbols(
        documents_by_uri.values(),
        metadata_registry=metadata_registry,
        symbol_ids=symbol_ids,
    )
    return tuple(definition.location for definition in definitions)


def references(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    metadata_registry: MetadataRegistry,
    uri: str,
    line: int,
    character: int,
    include_declaration: bool = True,
) -> tuple[Location, ...]:
    symbol_ids = symbol_ids_at_position(documents_by_uri, uri=uri, line=line, character=character)
    if not symbol_ids:
        return ()

    locations: list[Location] = []
    if include_declaration:
        locations.extend(
            definition.location
            for definition in definitions_for_symbols(
                documents_by_uri.values(),
                metadata_registry=metadata_registry,
                symbol_ids=symbol_ids,
            )
        )

    for document in documents_by_uri.values():
        for resolved_reference in document.analysis.resolved_references:
            if resolved_reference.symbol_id not in symbol_ids:
                continue
            locations.append(
                Location(
                    uri=resolved_reference.reference.uri, span=resolved_reference.reference.span
                )
            )

    return deduplicate_locations(locations)


def package_definition_locations(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> tuple[Location, ...]:
    document = documents_by_uri.get(uri)
    if document is None:
        return ()

    for package_require in document.facts.package_requires:
        if not package_require.span.contains(line=line, character=character):
            continue
        provided_locations = [
            Location(uri=package.uri, span=package.span)
            for package in workspace_index.provided_packages_for_name(package_require.name)
        ]
        if provided_locations:
            return deduplicate_locations(provided_locations)

        index_locations = [
            Location(uri=entry.uri, span=entry.span)
            for entry in workspace_index.package_index_entries_for_name(package_require.name)
        ]
        return deduplicate_locations(index_locations)

    return ()


def command_import_definition_locations(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    metadata_registry: MetadataRegistry,
    uri: str,
    line: int,
    character: int,
) -> tuple[Location, ...]:
    document = documents_by_uri.get(uri)
    if document is None:
        return ()

    for command_import in document.facts.command_imports:
        if not command_import.span.contains(line=line, character=character):
            continue
        return tuple(
            definition.location
            for definition in definitions_for_command_import(
                documents_by_uri.values(),
                metadata_registry=metadata_registry,
                command_import=command_import,
            )
        )

    return ()


def deduplicate_locations(locations: list[Location]) -> tuple[Location, ...]:
    deduplicated: dict[tuple[str, int, int], Location] = {}
    for location in locations:
        key = (location.uri, location.span.start.offset, location.span.end.offset)
        deduplicated.setdefault(key, location)
    return tuple(deduplicated.values())
