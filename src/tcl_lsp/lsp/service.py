from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from tcl_lsp.analysis import AnalysisResult, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.builtins import builtin_definition_targets
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
        self._scanned_package_roots: set[Path] = set()
        self._failed_background_documents: set[str] = set()

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
        self._ensure_package_documents_loaded()
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
        self._index_document(uri=uri, text=text, version=version)
        self._discover_package_roots(uri)
        self._ensure_package_documents_loaded()
        self._recompute_workspace_analyses()

    def _index_document(self, uri: str, text: str, version: int) -> None:
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

    def _discover_package_roots(self, uri: str) -> None:
        path = _source_id_to_path(uri)
        if path is None:
            return

        for package_root in _candidate_package_roots(path):
            resolved_root = package_root.resolve(strict=False)
            if resolved_root in self._scanned_package_roots:
                continue
            self._scanned_package_roots.add(resolved_root)
            self._scan_package_root(resolved_root)

    def _scan_package_root(self, package_root: Path) -> None:
        for pkg_index_path in sorted(package_root.rglob('pkgIndex.tcl')):
            try:
                text = _read_source_file(pkg_index_path)
            except OSError:
                continue
            pkg_index_uri = pkg_index_path.resolve(strict=False).as_uri()
            parse_result = self._parser.parse_document(path=pkg_index_uri, text=text)
            facts = self._extractor.extract(parse_result)
            self._workspace_index.update_package_index(
                pkg_index_uri,
                facts.package_index_entries,
            )

    def _ensure_package_documents_loaded(self) -> None:
        while True:
            loaded_document = False
            for document in tuple(self._documents.values()):
                for package_require in document.facts.package_requires:
                    for source_uri in self._workspace_index.package_source_uris(package_require.name):
                        if source_uri in self._documents:
                            continue
                        if source_uri in self._failed_background_documents:
                            continue
                        if self._load_background_document(source_uri):
                            loaded_document = True
                            break
                    if loaded_document:
                        break
                if loaded_document:
                    break
            if not loaded_document:
                return

    def _load_background_document(self, uri: str) -> bool:
        path = _source_id_to_path(uri)
        if path is None:
            self._failed_background_documents.add(uri)
            return False

        try:
            text = _read_source_file(path)
        except OSError:
            self._failed_background_documents.add(uri)
            return False

        self._index_document(uri=uri, text=text, version=0)
        self._discover_package_roots(uri)
        return True

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
            if definition.location.uri == uri
            and definition.location.span.contains(line=line, character=character)
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
        for definition in builtin_definition_targets():
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


def _candidate_package_roots(path: Path) -> tuple[Path, ...]:
    start_directory = path if path.is_dir() else path.parent
    direct_package_root: Path | None = None

    for directory in (start_directory, *start_directory.parents):
        if _has_pkgindex_children(directory):
            return (directory,)
        if direct_package_root is None and (directory / 'pkgIndex.tcl').is_file():
            direct_package_root = directory

    if direct_package_root is None:
        return ()
    return (direct_package_root,)


def _has_pkgindex_children(directory: Path) -> bool:
    try:
        for child in directory.iterdir():
            if child.is_dir() and (child / 'pkgIndex.tcl').is_file():
                return True
    except OSError:
        return False
    return False


def _source_id_to_path(source_id: str) -> Path | None:
    parsed = urlparse(source_id)
    if parsed.scheme == 'file':
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_id)


def _read_source_file(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ('utf-8', 'iso-8859-1'):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise AssertionError(f'Could not decode {path}: {last_error}')
