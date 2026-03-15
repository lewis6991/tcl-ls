from __future__ import annotations

from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location, Position, Span
from tcl_lsp.lsp.model import (
    DiagnosticDict,
    DocumentSymbolDict,
    HoverDict,
    LocationDict,
    MarkupContentDict,
    PositionDict,
    RangeDict,
)

_DIAGNOSTIC_SEVERITY_MAP = {
    'error': 1,
    'warning': 2,
    'information': 3,
    'hint': 4,
}
_DOCUMENT_SYMBOL_KIND_MAP = {
    'namespace': 3,
    'function': 12,
    'variable': 13,
}


def position_to_lsp(position: Position) -> PositionDict:
    return {
        'line': position.line,
        'character': position.character,
    }


def range_to_lsp(span: Span) -> RangeDict:
    return {
        'start': position_to_lsp(span.start),
        'end': position_to_lsp(span.end),
    }


def location_to_lsp(location: Location) -> LocationDict:
    return {
        'uri': location.uri,
        'range': range_to_lsp(location.span),
    }


def diagnostic_to_lsp(diagnostic: Diagnostic) -> DiagnosticDict:
    return {
        'range': range_to_lsp(diagnostic.span),
        'severity': _DIAGNOSTIC_SEVERITY_MAP[diagnostic.severity],
        'code': diagnostic.code,
        'source': diagnostic.source,
        'message': diagnostic.message,
    }


def hover_to_lsp(hover: HoverInfo) -> HoverDict:
    contents: MarkupContentDict = {
        'kind': 'markdown',
        'value': _hover_markdown(hover),
    }
    return {
        'contents': contents,
        'range': range_to_lsp(hover.span),
    }


def document_symbol_to_lsp(symbol: DocumentSymbol) -> DocumentSymbolDict:
    return {
        'name': symbol.name,
        'kind': _DOCUMENT_SYMBOL_KIND_MAP[symbol.kind],
        'range': range_to_lsp(symbol.span),
        'selectionRange': range_to_lsp(symbol.selection_span),
        'children': [document_symbol_to_lsp(child) for child in symbol.children],
    }


def _hover_markdown(hover: HoverInfo) -> str:
    signature, separator, remainder = hover.contents.partition('\n\n')
    if signature.startswith('proc '):
        if not separator:
            return f'```tcl\n{signature}\n```'
        return f'```tcl\n{signature}\n```\n\n{remainder}'

    if signature.startswith('builtin command '):
        command_name = signature.removeprefix('builtin command ')
        if not separator:
            return f'```tcl\n{command_name}\n```'
        return f'```tcl\n{command_name}\n```\n\n{remainder}'

    return hover.contents
