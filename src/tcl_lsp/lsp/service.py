from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import AnalysisResult, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.analysis.builtins import builtin_definition_targets
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.analysis.model import DefinitionTarget, DocumentFacts
from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location, Span
from tcl_lsp.lsp.semantic_tokens import encode_document_semantic_tokens
from tcl_lsp.metadata_paths import configure_metadata_paths
from tcl_lsp.parser import Parser, ParseResult
from tcl_lsp.project_config import configured_library_paths, configured_plugin_paths
from tcl_lsp.workspace import candidate_package_roots, read_source_file, source_id_to_path


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


class LanguageService:
    __slots__ = (
        '_documents',
        '_extractor',
        '_failed_background_documents',
        '_library_paths_by_uri',
        '_open_document_uris',
        '_parser',
        '_plugin_paths_by_uri',
        '_resolver',
        '_scanned_package_roots',
        '_workspace_index',
    )

    def __init__(
        self,
        parser: Parser | None = None,
        extractor: FactExtractor | None = None,
        workspace_index: WorkspaceIndex | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        configure_metadata_paths(())
        self._parser = Parser() if parser is None else parser
        self._extractor = FactExtractor(self._parser) if extractor is None else extractor
        self._workspace_index = WorkspaceIndex() if workspace_index is None else workspace_index
        self._resolver = Resolver() if resolver is None else resolver
        self._documents: dict[str, ManagedDocument] = {}
        self._scanned_package_roots: set[Path] = set()
        self._failed_background_documents: set[str] = set()
        self._open_document_uris: set[str] = set()
        self._plugin_paths_by_uri: dict[str, tuple[Path, ...]] = {}
        self._library_paths_by_uri: dict[str, tuple[Path, ...]] = {}

    def open_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),))
        return self.diagnostics(uri)

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),))
        return self.diagnostics(uri)

    def close_document(self, uri: str) -> tuple[Diagnostic, ...]:
        if uri not in self._documents:
            return ()

        previous_plugin_paths = self._active_plugin_paths()
        previous_library_paths = self._active_library_paths()
        self._open_document_uris.discard(uri)
        self._plugin_paths_by_uri.pop(uri, None)
        self._library_paths_by_uri.pop(uri, None)
        del self._documents[uri]
        self._workspace_index.remove(uri)

        if (
            self._active_plugin_paths() != previous_plugin_paths
            or self._active_library_paths() != previous_library_paths
        ):
            self._rebuild_documents()
            return ()

        self._ensure_background_documents_loaded()
        self._recompute_workspace_analyses()
        return ()

    def diagnostics(self, uri: str) -> tuple[Diagnostic, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()
        return document.analysis.diagnostics

    def definition(self, uri: str, line: int, character: int) -> tuple[Location, ...]:
        package_locations = self._package_definition_locations(uri, line, character)
        if package_locations:
            return package_locations

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

    def rename(
        self,
        uri: str,
        line: int,
        character: int,
        new_name: str,
    ) -> dict[str, tuple[RenameEdit, ...]] | None:
        if not _is_valid_rename_name(new_name):
            return None

        symbol_id = self._rename_symbol_id_at_position(uri, line, character)
        if symbol_id is None:
            return None

        target_kind = self._symbol_kind(symbol_id)
        if target_kind is None:
            return None

        edits_by_uri: dict[str, dict[tuple[int, int], RenameEdit]] = {}
        for document in self._documents.values():
            if target_kind == 'function':
                for procedure in document.facts.procedures:
                    if procedure.symbol_id != symbol_id:
                        continue
                    _add_rename_edit(
                        edits_by_uri,
                        uri=document.uri,
                        span=procedure.name_span,
                        new_text=_rename_command_text(
                            document.text[
                                procedure.name_span.start.offset : procedure.name_span.end.offset
                            ],
                            new_name,
                        ),
                    )
            else:
                for binding in document.facts.variable_bindings:
                    if binding.symbol_id != symbol_id:
                        continue
                    _add_rename_edit(
                        edits_by_uri,
                        uri=document.uri,
                        span=binding.span,
                        new_text=_rename_variable_text(
                            document.text[binding.span.start.offset : binding.span.end.offset],
                            new_name,
                        ),
                    )

            for resolved_reference in document.analysis.resolved_references:
                if resolved_reference.symbol_id != symbol_id:
                    continue
                if target_kind == 'function' and resolved_reference.reference.kind != 'command':
                    continue
                if target_kind == 'variable' and resolved_reference.reference.kind != 'variable':
                    continue
                reference_span = resolved_reference.reference.span
                reference_text = document.text[
                    reference_span.start.offset : reference_span.end.offset
                ]
                replacement = (
                    _rename_command_text(reference_text, new_name)
                    if target_kind == 'function'
                    else _rename_variable_text(reference_text, new_name)
                )
                _add_rename_edit(
                    edits_by_uri,
                    uri=document.uri,
                    span=reference_span,
                    new_text=replacement,
                )

        if not edits_by_uri:
            return None

        return {
            uri: tuple(
                edit
                for _, edit in sorted(
                    edits.items(),
                    key=lambda item: (item[1].span.start.offset, item[1].span.end.offset),
                )
            )
            for uri, edits in sorted(edits_by_uri.items())
        }

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

    def semantic_tokens(self, uri: str) -> tuple[int, ...] | None:
        document = self._documents.get(uri)
        if document is None:
            return None
        return encode_document_semantic_tokens(
            text=document.text,
            facts=document.facts,
            analysis=document.analysis,
        )

    def get_document(self, uri: str) -> ManagedDocument | None:
        return self._documents.get(uri)

    def load_documents(self, documents: Iterable[tuple[str, str, int]]) -> None:
        pending_documents = tuple(documents)
        if not pending_documents:
            return

        previous_plugin_paths = self._active_plugin_paths()
        previous_library_paths = self._active_library_paths()
        for uri, _, _ in pending_documents:
            self._open_document_uris.add(uri)
            self._plugin_paths_by_uri[uri] = self._configured_plugin_paths(uri)
            self._library_paths_by_uri[uri] = self._configured_library_paths(uri)

        if (
            self._active_plugin_paths() != previous_plugin_paths
            or self._active_library_paths() != previous_library_paths
        ):
            self._rebuild_documents(pending_documents)
            return

        for uri, text, version in pending_documents:
            self._index_document(uri=uri, text=text, version=version)
            self._discover_package_roots(uri)
        self._ensure_background_documents_loaded()
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
        path = source_id_to_path(uri)
        if path is None:
            return

        package_roots = (*candidate_package_roots(path), *self._library_paths_by_uri.get(uri, ()))
        for package_root in package_roots:
            resolved_root = package_root.resolve(strict=False)
            if resolved_root in self._scanned_package_roots:
                continue
            self._scanned_package_roots.add(resolved_root)
            self._scan_package_root(resolved_root)

    def _scan_package_root(self, package_root: Path) -> None:
        for pkg_index_path in sorted(package_root.rglob('pkgIndex.tcl')):
            try:
                text = read_source_file(pkg_index_path)
            except OSError:
                continue
            pkg_index_uri = pkg_index_path.resolve(strict=False).as_uri()
            parse_result = self._parser.parse_document(path=pkg_index_uri, text=text)
            facts = self._extractor.extract(parse_result)
            self._workspace_index.update_package_index(
                pkg_index_uri,
                facts.package_index_entries,
            )

    def _ensure_background_documents_loaded(self) -> None:
        while True:
            loaded_document = False
            for document in tuple(self._documents.values()):
                for source_uri in self._background_document_uris(document.facts):
                    if source_uri in self._documents:
                        continue
                    if source_uri in self._failed_background_documents:
                        continue
                    if self._load_background_document(source_uri):
                        loaded_document = True
                        break
                if loaded_document:
                    break
            if not loaded_document:
                return

    def _background_document_uris(self, facts: DocumentFacts) -> tuple[str, ...]:
        uris: dict[str, None] = {}
        for directive in facts.source_directives:
            uris.setdefault(directive.target_uri, None)
        for package_require in facts.package_requires:
            for source_uri in self._workspace_index.package_source_uris(package_require.name):
                uris.setdefault(source_uri, None)
        return tuple(uris)

    def _load_background_document(self, uri: str) -> bool:
        path = source_id_to_path(uri)
        if path is None:
            self._failed_background_documents.add(uri)
            return False

        try:
            text = read_source_file(path)
        except OSError:
            self._failed_background_documents.add(uri)
            return False

        self._index_document(uri=uri, text=text, version=0)
        self._discover_package_roots(uri)
        return True

    def _recompute_workspace_analyses(self) -> None:
        for uri, document in list(self._documents.items()):
            source_path = source_id_to_path(uri)
            additional_required_packages: frozenset[str]
            if source_path is None:
                additional_required_packages = frozenset()
            else:
                additional_required_packages = dependency_required_packages(
                    source_path,
                    document.facts,
                    self._workspace_index,
                )
            analysis = self._resolver.analyze(
                uri=uri,
                facts=document.facts,
                workspace_index=self._workspace_index,
                additional_required_packages=additional_required_packages,
            )
            self._documents[uri] = ManagedDocument(
                uri=document.uri,
                version=document.version,
                text=document.text,
                parse_result=document.parse_result,
                facts=document.facts,
                analysis=analysis,
            )

    def _configured_plugin_paths(self, uri: str) -> tuple[Path, ...]:
        path = source_id_to_path(uri)
        if path is None:
            return ()
        return configured_plugin_paths(path)

    def _configured_library_paths(self, uri: str) -> tuple[Path, ...]:
        path = source_id_to_path(uri)
        if path is None:
            return ()
        return configured_library_paths(path)

    def _active_plugin_paths(self) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in self._open_document_uris:
            for plugin_path in self._plugin_paths_by_uri.get(uri, ()):
                active_paths.setdefault(plugin_path, None)
        return tuple(active_paths)

    def _active_library_paths(self) -> tuple[Path, ...]:
        active_paths: dict[Path, None] = {}
        for uri in self._open_document_uris:
            for library_path in self._library_paths_by_uri.get(uri, ()):
                active_paths.setdefault(library_path, None)
        return tuple(active_paths)

    def _rebuild_documents(self, pending_documents: Iterable[tuple[str, str, int]] = ()) -> None:
        snapshots: dict[str, tuple[str, int]] = {}
        for uri in self._open_document_uris:
            document = self._documents.get(uri)
            if document is None:
                continue
            snapshots[uri] = (document.text, document.version)
        for uri, text, version in pending_documents:
            snapshots[uri] = (text, version)

        configure_metadata_paths(self._active_plugin_paths())
        self._documents = {}
        self._workspace_index = WorkspaceIndex()
        self._scanned_package_roots = set()
        self._failed_background_documents = set()

        for uri, (text, version) in snapshots.items():
            self._index_document(uri=uri, text=text, version=version)
            self._discover_package_roots(uri)

        self._ensure_background_documents_loaded()
        self._recompute_workspace_analyses()

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

    def _package_definition_locations(
        self,
        uri: str,
        line: int,
        character: int,
    ) -> tuple[Location, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()

        for package_require in document.facts.package_requires:
            if not package_require.span.contains(line=line, character=character):
                continue
            provided_locations = [
                Location(uri=package.uri, span=package.span)
                for package in self._workspace_index.provided_packages_for_name(
                    package_require.name
                )
            ]
            if provided_locations:
                return _deduplicate_locations(provided_locations)

            index_locations = [
                Location(uri=entry.uri, span=entry.span)
                for entry in self._workspace_index.package_index_entries_for_name(
                    package_require.name
                )
            ]
            return _deduplicate_locations(index_locations)

        return ()

    def _rename_symbol_id_at_position(self, uri: str, line: int, character: int) -> str | None:
        symbol_ids = self._symbol_ids_at_position(uri, line, character)
        if len(symbol_ids) != 1:
            return None

        symbol_id = symbol_ids[0]
        if symbol_id.startswith('builtin::'):
            return None
        return symbol_id

    def _symbol_kind(self, symbol_id: str) -> str | None:
        for document in self._documents.values():
            for procedure in document.facts.procedures:
                if procedure.symbol_id == symbol_id:
                    return 'function'
            for binding in document.facts.variable_bindings:
                if binding.symbol_id == symbol_id:
                    return 'variable'
        return None

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


def _add_rename_edit(
    edits_by_uri: dict[str, dict[tuple[int, int], RenameEdit]],
    *,
    uri: str,
    span: Span,
    new_text: str,
) -> None:
    edits_for_uri = edits_by_uri.setdefault(uri, {})
    edits_for_uri.setdefault(
        (span.start.offset, span.end.offset),
        RenameEdit(span=span, new_text=new_text),
    )


def _is_valid_rename_name(new_name: str) -> bool:
    return bool(new_name) and ':' not in new_name and is_simple_name(new_name)


def _rename_command_text(text: str, new_name: str) -> str:
    if text.startswith('{') and text.endswith('}'):
        return '{' + _rename_command_name_body(text[1:-1], new_name) + '}'
    if text.startswith('"') and text.endswith('"'):
        return '"' + _rename_command_name_body(text[1:-1], new_name) + '"'
    return _rename_command_name_body(text, new_name)


def _rename_command_name_body(text: str, new_name: str) -> str:
    prefix, separator, _ = text.rpartition('::')
    if separator:
        return f'{prefix}{separator}{new_name}'
    return new_name


def _rename_variable_text(text: str, new_name: str) -> str:
    if text.startswith('${') and text.endswith('}'):
        return '${' + _rename_variable_name_body(text[2:-1], new_name) + '}'
    if text.startswith('$'):
        return '$' + _rename_variable_name_body(text[1:], new_name)
    if text.startswith('{') and text.endswith('}'):
        return '{' + _rename_variable_name_body(text[1:-1], new_name) + '}'
    if text.startswith('"') and text.endswith('"'):
        return '"' + _rename_variable_name_body(text[1:-1], new_name) + '"'
    return _rename_variable_name_body(text, new_name)


def _rename_variable_name_body(text: str, new_name: str) -> str:
    suffix = ''
    open_paren = text.find('(')
    if open_paren > 0 and text.endswith(')'):
        suffix = text[open_paren:]
        text = text[:open_paren]

    prefix, separator, _ = text.rpartition('::')
    if separator:
        return f'{prefix}{separator}{new_name}{suffix}'
    return new_name + suffix
