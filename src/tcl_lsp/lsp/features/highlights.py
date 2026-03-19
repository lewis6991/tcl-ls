from __future__ import annotations

from collections.abc import Mapping

from lsprotocol import types

from tcl_lsp.common import Span, lsp_range
from tcl_lsp.lsp.features.symbols import symbol_ids_at_position
from tcl_lsp.lsp.state import ManagedDocument


def document_highlights(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
) -> tuple[types.DocumentHighlight, ...]:
    document = documents_by_uri.get(uri)
    if document is None:
        return ()

    symbol_ids = symbol_ids_at_position(documents_by_uri, uri=uri, line=line, character=character)
    if not symbol_ids:
        return ()

    highlights: list[types.DocumentHighlight] = []
    seen: set[tuple[int, int, int, int]] = set()

    for definition in document.analysis.definitions:
        if definition.symbol_id not in symbol_ids or definition.location.uri != uri:
            continue
        _add_highlight(
            highlights,
            seen,
            definition.span,
            kind=types.DocumentHighlightKind.Write,
        )

    for resolved_reference in document.analysis.resolved_references:
        if (
            resolved_reference.symbol_id not in symbol_ids
            or resolved_reference.reference.uri != uri
        ):
            continue
        _add_highlight(
            highlights,
            seen,
            resolved_reference.reference.span,
            kind=(
                types.DocumentHighlightKind.Read
                if resolved_reference.reference.kind == 'variable'
                else types.DocumentHighlightKind.Text
            ),
        )

    return tuple(highlights)


def _add_highlight(
    highlights: list[types.DocumentHighlight],
    seen: set[tuple[int, int, int, int]],
    span: Span,
    *,
    kind: types.DocumentHighlightKind,
) -> None:
    key = (
        span.start.line,
        span.start.character,
        span.end.line,
        span.end.character,
    )
    if key in seen:
        return
    seen.add(key)
    highlights.append(types.DocumentHighlight(range=lsp_range(span), kind=kind))
