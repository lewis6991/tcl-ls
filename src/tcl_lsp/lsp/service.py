from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis import AnalysisResult, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.model import DefinitionTarget, DocumentFacts
from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location
from tcl_lsp.parser import Parser, ParseResult


@dataclass(frozen=True, slots=True)
class ManagedDocument:
    uri: str
    version: int
    text: str
    parse_result: ParseResult
    facts: DocumentFacts
    analysis: AnalysisResult


class LanguageService:
    def __init__(
        self,
        parser: Parser | None = None,
        extractor: FactExtractor | None = None,
        workspace_index: WorkspaceIndex | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._parser = Parser() if parser is None else parser
        self._extractor = FactExtractor(self._parser) if extractor is None else extractor
        self._workspace_index = WorkspaceIndex() if workspace_index is None else workspace_index
        self._resolver = Resolver() if resolver is None else resolver
        self._documents: dict[str, ManagedDocument] = {}

    def open_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self._upsert_document(uri=uri, text=text, version=version)
        return self.diagnostics(uri)

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self._upsert_document(uri=uri, text=text, version=version)
        return self.diagnostics(uri)

    def close_document(self, uri: str) -> tuple[Diagnostic, ...]:
        if uri not in self._documents:
            return ()
        del self._documents[uri]
        self._workspace_index.remove(uri)
        self._recompute_workspace_analyses()
        return ()

    def diagnostics(self, uri: str) -> tuple[Diagnostic, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def definition(self, uri: str, line: int, character: int) -> tuple[Location, ...]:
        symbol_ids = self._symbol_ids_at_position(uri, line, character)
        if not symbol_ids:
            return ()
        definitions = self._definitions_for_symbols(symbol_ids)
        return tuple(definition.location for definition in definitions)

    def references(
        self,
        uri: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> tuple[Location, ...]:
        symbol_ids = self._symbol_ids_at_position(uri, line, character)
        if not symbol_ids:
            return ()

        locations: list[Location] = []
        if include_declaration:
            locations.extend(
                definition.location for definition in self._definitions_for_symbols(symbol_ids)
            )

        for document in self._documents.values():
            for resolved_reference in document.analysis.resolved_references:
                if resolved_reference.symbol_id not in symbol_ids:
                    continue
                locations.append(
                    Location(
                        uri=resolved_reference.reference.uri, span=resolved_reference.reference.span
                    )
                )

        return _deduplicate_locations(locations)

    def hover(self, uri: str, line: int, character: int) -> HoverInfo | None:
        document = self._documents.get(uri)
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

    def document_symbols(self, uri: str) -> tuple[DocumentSymbol, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()
        return document.analysis.document_symbols

    def get_document(self, uri: str) -> ManagedDocument | None:
        return self._documents.get(uri)

    def _upsert_document(self, uri: str, text: str, version: int) -> None:
        parse_result = self._parser.parse_document(path=uri, text=text)
        facts = self._extractor.extract(parse_result)
        self._documents[uri] = ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            parse_result=parse_result,
            facts=facts,
            analysis=_empty_analysis(uri, facts.document_symbols),
        )
        self._workspace_index.update(uri, facts)
        self._recompute_workspace_analyses()

    def _recompute_workspace_analyses(self) -> None:
        for uri, document in list(self._documents.items()):
            analysis = self._resolver.analyze(
                uri=uri, facts=document.facts, workspace_index=self._workspace_index
            )
            self._documents[uri] = ManagedDocument(
                uri=document.uri,
                version=document.version,
                text=document.text,
                parse_result=document.parse_result,
                facts=document.facts,
                analysis=analysis,
            )

    def _symbol_ids_at_position(self, uri: str, line: int, character: int) -> tuple[str, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()

        direct_matches = [
            definition.symbol_id
            for definition in document.analysis.definitions
            if definition.location.span.contains(line=line, character=character)
        ]
        if direct_matches:
            return tuple(dict.fromkeys(direct_matches))

        resolved_matches: list[str] = []
        for resolution in document.analysis.resolutions:
            if resolution.reference.span.contains(line=line, character=character):
                resolved_matches.extend(resolution.target_symbol_ids)
        return tuple(dict.fromkeys(resolved_matches))

    def _definitions_for_symbols(self, symbol_ids: tuple[str, ...]) -> tuple[DefinitionTarget, ...]:
        definitions: list[DefinitionTarget] = []
        seen: set[str] = set()
        for document in self._documents.values():
            for definition in document.analysis.definitions:
                if definition.symbol_id not in symbol_ids or definition.symbol_id in seen:
                    continue
                seen.add(definition.symbol_id)
                definitions.append(definition)
        return tuple(definitions)


def _deduplicate_locations(locations: list[Location]) -> tuple[Location, ...]:
    deduplicated: dict[tuple[str, int, int], Location] = {}
    for location in locations:
        key = (location.uri, location.span.start.offset, location.span.end.offset)
        deduplicated.setdefault(key, location)
    return tuple(deduplicated.values())


def _empty_analysis(uri: str, document_symbols: tuple[DocumentSymbol, ...]) -> AnalysisResult:
    return AnalysisResult(
        uri=uri,
        diagnostics=(),
        definitions=(),
        resolutions=(),
        resolved_references=(),
        document_symbols=document_symbols,
        hovers=(),
    )
