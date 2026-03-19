from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import AnalysisResult, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.builtins import builtin_definition_targets
from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.analysis.model import CommandImport, DefinitionTarget, DocumentFacts
from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location, Span
from tcl_lsp.lsp.semantic_tokens import encode_document_semantic_tokens
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataRegistry,
    create_metadata_registry,
)
from tcl_lsp.parser import Parser, ParseResult
from tcl_lsp.project.config import configured_library_paths, configured_plugin_paths
from tcl_lsp.project.indexing import (
    load_dependency_documents,
    reachable_document_uris,
    scan_package_root,
)
from tcl_lsp.project.paths import candidate_package_roots, read_source_file, source_id_to_path


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


class LanguageService:
    __slots__ = (
        '_documents',
        '_extractor',
        '_library_paths_by_uri',
        '_metadata_registry',
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
        metadata_registry: MetadataRegistry | None = None,
    ) -> None:
        extracted_metadata_registry = extractor.metadata_registry if extractor is not None else None
        resolver_metadata_registry = resolver.metadata_registry if resolver is not None else None
        resolved_metadata_registry = (
            metadata_registry
            if metadata_registry is not None
            else extracted_metadata_registry
            or resolver_metadata_registry
            or DEFAULT_METADATA_REGISTRY
        )
        if (
            extracted_metadata_registry is not None
            and extracted_metadata_registry != resolved_metadata_registry
        ):
            raise ValueError('Extractor metadata registry does not match LanguageService.')
        if (
            resolver_metadata_registry is not None
            and resolver_metadata_registry != resolved_metadata_registry
        ):
            raise ValueError('Resolver metadata registry does not match LanguageService.')

        self._metadata_registry = resolved_metadata_registry
        self._parser = Parser() if parser is None else parser
        self._extractor = (
            FactExtractor(self._parser, metadata_registry=self._metadata_registry)
            if extractor is None
            else extractor
        )
        self._workspace_index = WorkspaceIndex() if workspace_index is None else workspace_index
        self._resolver = (
            Resolver(metadata_registry=self._metadata_registry) if resolver is None else resolver
        )
        self._documents: dict[str, ManagedDocument] = {}
        self._scanned_package_roots: set[Path] = set()
        self._open_document_uris: set[str] = set()
        self._plugin_paths_by_uri: dict[str, tuple[Path, ...]] = {}
        self._library_paths_by_uri: dict[str, tuple[Path, ...]] = {}

    def open_document(
        self,
        uri: str,
        text: str,
        version: int,
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),), progress=progress)
        return self.diagnostics(uri)

    def change_document(self, uri: str, text: str, version: int) -> tuple[Diagnostic, ...]:
        self.load_documents(((uri, text, version),))
        return self.diagnostics(uri)

    def close_document(self, uri: str) -> tuple[Diagnostic, ...]:
        if uri not in self._documents:
            return ()

        self._open_document_uris.discard(uri)
        self._plugin_paths_by_uri.pop(uri, None)
        self._library_paths_by_uri.pop(uri, None)
        self._rebuild_documents()
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

        command_import_locations = self._command_import_definition_locations(uri, line, character)
        if command_import_locations:
            return command_import_locations

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

    def load_documents(
        self,
        documents: Iterable[tuple[str, str, int]],
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> None:
        pending_documents = tuple(documents)
        if not pending_documents:
            return

        for uri, _, _ in pending_documents:
            self._open_document_uris.add(uri)
            self._plugin_paths_by_uri[uri] = self._configured_plugin_paths(uri)
            self._library_paths_by_uri[uri] = self._configured_library_paths(uri)

        self._report_progress(progress, 'Rebuilding workspace index', 10)
        self._rebuild_documents(pending_documents, progress=progress)

    def _index_document(self, uri: str, text: str, version: int) -> None:
        document = self._build_document(uri=uri, text=text, version=version)
        self._store_document(document)

    def _build_document(self, *, uri: str, text: str, version: int) -> ManagedDocument:
        parse_result = self._parser.parse_document(path=uri, text=text)
        facts = self._extractor.extract(parse_result)
        return ManagedDocument(
            uri=uri,
            version=version,
            text=text,
            parse_result=parse_result,
            facts=facts,
            analysis=_empty_analysis(uri, facts.document_symbols),
        )

    def _store_document(self, document: ManagedDocument) -> None:
        self._documents[document.uri] = document
        self._workspace_index.update(document.uri, document.facts)

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
        scan_package_root(
            package_root,
            parser=self._parser,
            extractor=self._extractor,
            workspace_index=self._workspace_index,
        )

    def _ensure_background_documents_loaded(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        start_percentage: int = 50,
        end_percentage: int = 75,
    ) -> None:
        def load_document(uri: str) -> ManagedDocument | None:
            return self._load_document_from_uri(uri, version=0)

        loaded_documents = load_dependency_documents(
            self._documents,
            workspace_index=self._workspace_index,
            describe_document=_managed_document_details,
            load_document=load_document,
            metadata_registry=self._metadata_registry,
            on_document_loaded=lambda document: self._discover_package_roots(document.uri),
        )

        loaded_background_documents = 0
        for _ in loaded_documents:
            loaded_background_documents += 1
            self._report_progress(
                progress,
                f'Loading workspace dependencies ({loaded_background_documents})',
                min(end_percentage, start_percentage + loaded_background_documents),
            )

    def _load_document_from_uri(self, uri: str, *, version: int) -> ManagedDocument | None:
        path = source_id_to_path(uri)
        if path is None:
            return None

        try:
            text = read_source_file(path)
        except OSError:
            return None

        return self._build_document(uri=uri, text=text, version=version)

    def _recompute_workspace_analyses(
        self,
        *,
        progress: IndexingProgressCallback | None = None,
        start_percentage: int = 75,
        end_percentage: int = 95,
    ) -> None:
        documents = list(self._documents.items())
        total_documents = len(documents)
        for index, (uri, document) in enumerate(documents, start=1):
            analysis_workspace_index = self._analysis_workspace_index(uri)
            source_path = source_id_to_path(uri)
            additional_required_packages: frozenset[str]
            if source_path is None:
                additional_required_packages = frozenset()
            else:
                additional_required_packages = dependency_required_packages(
                    source_path,
                    document.facts,
                    analysis_workspace_index,
                    metadata_registry=self._metadata_registry,
                )
            analysis = self._resolver.analyze(
                uri=uri,
                facts=document.facts,
                workspace_index=analysis_workspace_index,
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
            self._report_progress(
                progress,
                f'Analyzing workspace ({index}/{total_documents})',
                _progress_percentage(
                    index=index,
                    total=total_documents,
                    start=start_percentage,
                    end=end_percentage,
                ),
            )

    def _analysis_workspace_index(self, root_uri: str) -> WorkspaceIndex:
        workspace_index = WorkspaceIndex()
        for pkg_index_uri, entries in self._workspace_index.package_indexes():
            workspace_index.update_package_index(pkg_index_uri, entries)
        for uri in self._reachable_analysis_uris(root_uri):
            document = self._documents.get(uri)
            if document is None:
                continue
            workspace_index.update(uri, document.facts)
        return workspace_index

    def _reachable_analysis_uris(self, root_uri: str) -> tuple[str, ...]:
        return reachable_document_uris(
            root_uri,
            documents_by_uri=self._documents,
            workspace_index=self._workspace_index,
            describe_document=_managed_document_details,
            metadata_registry=self._metadata_registry,
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

    def _rebuild_documents(
        self,
        pending_documents: Iterable[tuple[str, str, int]] = (),
        *,
        progress: IndexingProgressCallback | None = None,
    ) -> None:
        snapshots: dict[str, tuple[str, int]] = {}
        for uri in self._open_document_uris:
            document = self._documents.get(uri)
            if document is None:
                continue
            snapshots[uri] = (document.text, document.version)
        for uri, text, version in pending_documents:
            snapshots[uri] = (text, version)

        self._set_metadata_registry(create_metadata_registry(self._active_plugin_paths()))
        self._documents = {}
        self._workspace_index = WorkspaceIndex()
        self._scanned_package_roots = set()

        total_snapshots = len(snapshots)
        for index, (uri, (text, version)) in enumerate(snapshots.items(), start=1):
            self._index_document(uri=uri, text=text, version=version)
            self._discover_package_roots(uri)
            self._report_progress(
                progress,
                f'Indexing workspace files ({index}/{total_snapshots})',
                _progress_percentage(
                    index=index,
                    total=total_snapshots,
                    start=20,
                    end=45,
                ),
            )

        self._report_progress(progress, 'Loading workspace dependencies', 50)
        self._ensure_background_documents_loaded(
            progress=progress,
            start_percentage=50,
            end_percentage=75,
        )
        self._recompute_workspace_analyses(
            progress=progress,
            start_percentage=75,
            end_percentage=95,
        )

    def _report_progress(
        self,
        progress: IndexingProgressCallback | None,
        message: str,
        percentage: int,
    ) -> None:
        if progress is None:
            return
        progress(message, percentage)

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

    def _command_import_definition_locations(
        self,
        uri: str,
        line: int,
        character: int,
    ) -> tuple[Location, ...]:
        document = self._documents.get(uri)
        if document is None:
            return ()

        for command_import in document.facts.command_imports:
            if not command_import.span.contains(line=line, character=character):
                continue
            return tuple(
                definition.location
                for definition in self._definitions_for_command_import(command_import)
            )

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

    def _definitions_for_command_import(
        self,
        command_import: CommandImport,
    ) -> tuple[DefinitionTarget, ...]:
        definitions: list[DefinitionTarget] = []
        seen: set[str] = set()
        target_name = _qualified_command_name(command_import.target_name)

        def add_definition(definition: DefinitionTarget) -> None:
            if definition.kind != 'function':
                return
            if definition.symbol_id in seen:
                return
            seen.add(definition.symbol_id)
            definitions.append(definition)

        for document in self._documents.values():
            for definition in document.analysis.definitions:
                qualified_name = _qualified_command_name(definition.name)
                if command_import.kind == 'exact':
                    if qualified_name != target_name:
                        continue
                elif not _is_direct_namespace_member(qualified_name, target_name):
                    continue
                add_definition(definition)

        for definition in builtin_definition_targets(metadata_registry=self._metadata_registry):
            qualified_name = _qualified_command_name(definition.name)
            if command_import.kind == 'exact':
                if qualified_name != target_name:
                    continue
            elif not _is_direct_namespace_member(qualified_name, target_name):
                continue
            add_definition(definition)

        return tuple(definitions)

    def _set_metadata_registry(self, metadata_registry: MetadataRegistry) -> None:
        if metadata_registry == self._metadata_registry:
            return

        self._extractor.close()
        self._metadata_registry = metadata_registry
        self._extractor = FactExtractor(self._parser, metadata_registry=metadata_registry)
        self._resolver = Resolver(metadata_registry=metadata_registry)

    def _definitions_for_symbols(self, symbol_ids: tuple[str, ...]) -> tuple[DefinitionTarget, ...]:
        definitions: list[DefinitionTarget] = []
        seen: set[str] = set()
        for document in self._documents.values():
            for definition in document.analysis.definitions:
                if definition.symbol_id not in symbol_ids or definition.symbol_id in seen:
                    continue
                seen.add(definition.symbol_id)
                definitions.append(definition)
        for definition in builtin_definition_targets(metadata_registry=self._metadata_registry):
            if definition.symbol_id not in symbol_ids or definition.symbol_id in seen:
                continue
            seen.add(definition.symbol_id)
            definitions.append(definition)
        return tuple(definitions)


def _managed_document_details(document: ManagedDocument) -> tuple[str, Path | None, DocumentFacts]:
    return (document.uri, source_id_to_path(document.uri), document.facts)


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


def _qualified_command_name(name: str) -> str:
    if name.startswith('::'):
        return name
    return f'::{name}'


def _is_direct_namespace_member(qualified_name: str, namespace: str) -> bool:
    if namespace == '::':
        return qualified_name.startswith('::') and '::' not in qualified_name[2:]

    prefix = namespace + '::'
    if not qualified_name.startswith(prefix):
        return False
    return '::' not in qualified_name[len(prefix) :]


def _progress_percentage(*, index: int, total: int, start: int, end: int) -> int:
    if total <= 0 or start >= end:
        return end
    completed = (index * (end - start)) // total
    return min(end, start + completed)
