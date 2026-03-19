from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from lsprotocol import types

from tcl_lsp.analysis.model import DefinitionTarget, NamespaceScope
from tcl_lsp.common import SymbolKind, lsp_location
from tcl_lsp.lsp.state import ManagedDocument


def workspace_symbols(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    query: str,
) -> tuple[types.WorkspaceSymbol, ...]:
    normalized_query = query.strip().casefold()
    symbols: list[types.WorkspaceSymbol] = []
    seen: set[tuple[str, str, int, int]] = set()

    for document in documents_by_uri.values():
        for namespace in document.facts.namespaces:
            if not _matches_query(namespace.qualified_name, normalized_query):
                continue
            location = lsp_location(namespace.uri, namespace.selection_span)
            key = (
                'namespace',
                namespace.qualified_name,
                location.range.start.line,
                location.range.start.character,
            )
            if key in seen:
                continue
            seen.add(key)
            symbols.append(
                types.WorkspaceSymbol(
                    name=namespace.qualified_name,
                    kind=types.SymbolKind.Namespace,
                    location=location,
                    container_name=_container_name_for_namespace(namespace),
                )
            )

        for definition in document.analysis.definitions:
            if not _matches_query(definition.name, normalized_query):
                continue
            location = definition.location
            key = (
                definition.symbol_id,
                definition.name,
                location.range.start.line,
                location.range.start.character,
            )
            if key in seen:
                continue
            seen.add(key)
            symbols.append(
                types.WorkspaceSymbol(
                    name=definition.name,
                    kind=_workspace_symbol_kind(definition.kind),
                    location=location,
                    container_name=_container_name_for_definition(definition),
                )
            )

    return tuple(
        sorted(
            symbols,
            key=lambda symbol: (
                not _query_prefix_match(symbol.name, normalized_query),
                symbol.name.casefold(),
                cast(types.Location, symbol.location).uri,
                cast(types.Location, symbol.location).range.start.line,
                cast(types.Location, symbol.location).range.start.character,
            ),
        )
    )


def _matches_query(name: str, normalized_query: str) -> bool:
    if not normalized_query:
        return True

    normalized_name = name.casefold()
    if normalized_query in normalized_name:
        return True
    tail = name.rsplit('::', 1)[-1].casefold()
    return normalized_query in tail


def _query_prefix_match(name: str, normalized_query: str) -> bool:
    if not normalized_query:
        return True

    normalized_name = name.casefold()
    if normalized_name.startswith(normalized_query):
        return True
    tail = name.rsplit('::', 1)[-1].casefold()
    return tail.startswith(normalized_query)


def _workspace_symbol_kind(kind: SymbolKind) -> types.SymbolKind:
    if kind == 'namespace':
        return types.SymbolKind.Namespace
    if kind == 'function':
        return types.SymbolKind.Function
    return types.SymbolKind.Variable


def _container_name_for_definition(definition: DefinitionTarget) -> str | None:
    if definition.kind == 'function':
        return _container_name(definition.name)
    return None


def _container_name_for_namespace(namespace: NamespaceScope) -> str | None:
    return _container_name(namespace.qualified_name)


def _container_name(name: str) -> str | None:
    stripped_name = name.removeprefix('::')
    if '::' not in stripped_name:
        return None
    return '::' + stripped_name.rsplit('::', 1)[0]
