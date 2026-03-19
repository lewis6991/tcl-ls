from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import AnalysisResult
from tcl_lsp.analysis.model import DocumentFacts
from tcl_lsp.common import DocumentSymbol, Span
from tcl_lsp.parser import ParseResult
from tcl_lsp.project.paths import source_id_to_path


@dataclass(frozen=True, slots=True)
class ManagedDocument:
    uri: str
    version: int
    text: str
    parse_result: ParseResult
    facts: DocumentFacts
    analysis: AnalysisResult


@dataclass(frozen=True, slots=True)
class RenameEdit:
    span: Span
    new_text: str


type IndexingProgressCallback = Callable[[str, int], None]


def managed_document_details(document: ManagedDocument) -> tuple[str, Path | None, DocumentFacts]:
    return (document.uri, source_id_to_path(document.uri), document.facts)


def empty_analysis(uri: str, document_symbols: tuple[DocumentSymbol, ...]) -> AnalysisResult:
    return AnalysisResult(
        uri=uri,
        diagnostics=(),
        definitions=(),
        resolutions=(),
        resolved_references=(),
        document_symbols=document_symbols,
        hovers=(),
    )
