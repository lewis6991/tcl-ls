from __future__ import annotations

from tcl_lsp.common import (
    Diagnostic as CommonDiagnostic,
)
from tcl_lsp.common import (
    DocumentSymbol as CommonDocumentSymbol,
)
from tcl_lsp.common import (
    HoverInfo,
    Span,
)
from tcl_lsp.common import (
    Location as CommonLocation,
)
from tcl_lsp.lsp.model import (
    LspDiagnostic,
    LspDocumentSymbol,
    LspHover,
    LspLocation,
    LspRange,
    MarkupContent,
)


def range_to_lsp(span: Span) -> LspRange:
    return LspRange.model_validate(span, from_attributes=True)


def location_to_lsp(location: CommonLocation) -> LspLocation:
    return LspLocation.model_validate(location, from_attributes=True)


def diagnostic_to_lsp(diagnostic: CommonDiagnostic) -> LspDiagnostic:
    return LspDiagnostic.model_validate(diagnostic, from_attributes=True)


def hover_to_lsp(hover: HoverInfo) -> LspHover:
    return LspHover(
        contents=MarkupContent(kind='markdown', value=_hover_markdown(hover)),
        range=range_to_lsp(hover.span),
    )


def document_symbol_to_lsp(symbol: CommonDocumentSymbol) -> LspDocumentSymbol:
    return LspDocumentSymbol.model_validate(symbol, from_attributes=True)


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
