from __future__ import annotations

from collections.abc import Mapping

from tcl_lsp.common import HoverInfo
from tcl_lsp.lsp.state import ManagedDocument


def hover(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
) -> HoverInfo | None:
    document = documents_by_uri.get(uri)
    if document is None:
        return None

    matches = [
        hover
        for hover in document.analysis.hovers
        if hover.span.contains(line=line, character=character)
    ]
    if not matches:
        return None
    return min(matches, key=lambda hover: hover.span.end.offset - hover.span.start.offset)
