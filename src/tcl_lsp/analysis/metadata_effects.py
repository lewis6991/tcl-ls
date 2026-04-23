from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from tcl_lsp.analysis.facts import FactExtractor
from tcl_lsp.analysis.facts.utils import normalize_command_name
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    MetadataContext,
    MetadataOption,
    MetadataPackage,
    MetadataSelector,
    MetadataSource,
    SourceBase,
    file_scoped_annotated_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.analysis.model import CommandCall, DocumentFacts, ProcDecl
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataRegistry,
)
from tcl_lsp.parser import Parser
from tcl_lsp.project.paths import source_id_to_path


@dataclass(frozen=True, slots=True)
class MetadataDependencyOverlay:
    source_uris: tuple[str, ...]
    required_packages: frozenset[str]


def metadata_dependency_overlay(
    source_path: Path,
    facts: DocumentFacts,
    workspace_index: WorkspaceIndex,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> MetadataDependencyOverlay:
    scanner = _DependencyScanner(
        source_path=source_path,
        workspace_index=workspace_index,
        metadata_registry=metadata_registry,
    )
    scanner.scan_facts(facts)
    return MetadataDependencyOverlay(
        source_uris=tuple(scanner.source_uris),
        required_packages=frozenset(scanner.required_packages),
    )


def dependency_required_packages(
    source_path: Path,
    facts: DocumentFacts,
    workspace_index: WorkspaceIndex,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> frozenset[str]:
    documents_by_uri = {document.uri: document for document in workspace_index.documents()}
    pending_documents: list[tuple[Path, DocumentFacts]] = [(source_path, facts)]
    visited_uris: set[str] = set()
    required_packages: set[str] = set()

    while pending_documents:
        current_path, current_facts = pending_documents.pop()
        if current_facts.uri in visited_uris:
            continue
        visited_uris.add(current_facts.uri)

        overlay = metadata_dependency_overlay(
            current_path,
            current_facts,
            workspace_index,
            metadata_registry=metadata_registry,
        )
        package_names = {
            package_require.name for package_require in current_facts.package_requires
        } | set(overlay.required_packages)
        required_packages.update(package_names)

        for source_uri in overlay.source_uris:
            if source_uri in visited_uris:
                continue
            nested_path = source_id_to_path(source_uri)
            nested_facts = documents_by_uri.get(source_uri)
            if nested_path is None or nested_facts is None:
                continue
            pending_documents.append((nested_path, nested_facts))

        for package_name in package_names:
            for source_uri in workspace_index.package_source_uris(package_name):
                if source_uri in visited_uris:
                    continue
                nested_path = source_id_to_path(source_uri)
                nested_facts = documents_by_uri.get(source_uri)
                if nested_path is None or nested_facts is None:
                    continue
                pending_documents.append((nested_path, nested_facts))

    return frozenset(required_packages)


@metadata_lru_cache(maxsize=1)
def _candidate_effect_command_names(metadata_registry: MetadataRegistry) -> frozenset[str]:
    candidates: set[str] = set()
    for _, command_name in _metadata_command_effects(metadata_registry).keys():
        tail = command_name.rsplit('::', 1)[-1]
        candidates.add(tail)
        candidates.add(command_name)
    return frozenset(candidates)


@metadata_lru_cache(maxsize=1)
def _metadata_command_effects(
    metadata_registry: MetadataRegistry,
) -> dict[tuple[str, str], MetadataCommand]:
    effects_by_key = {
        key: metadata_command
        for key, metadata_command in file_scoped_annotated_metadata_commands(
            metadata_registry=metadata_registry
        ).items()
        if any(
            isinstance(annotation, (MetadataPackage, MetadataContext, MetadataSource))
            for annotation in metadata_command.annotations
        )
    }

    if not effects_by_key:
        raise RuntimeError('No metadata effect entries were loaded.')
    return effects_by_key


@lru_cache(maxsize=4)
def _embedded_script_services(metadata_registry: MetadataRegistry) -> tuple[Parser, FactExtractor]:
    parser = Parser()
    return parser, FactExtractor(parser, metadata_registry=metadata_registry)


@dataclass(slots=True)
class _DependencyScanner:
    source_path: Path
    workspace_index: WorkspaceIndex
    metadata_registry: MetadataRegistry
    source_uris: dict[str, None] = field(init=False, default_factory=dict)
    required_packages: set[str] = field(init=False, default_factory=set)

    def scan_facts(self, facts: DocumentFacts) -> None:
        candidate_names = _candidate_effect_command_names(self.metadata_registry)
        for directive in facts.source_directives:
            self.source_uris.setdefault(directive.target_uri, None)
        for package_require in facts.package_requires:
            self.required_packages.add(package_require.name)
        for command_call in facts.command_calls:
            if command_call.name not in candidate_names:
                continue
            self._scan_command_call(command_call)

    def _scan_command_call(self, command_call: CommandCall) -> None:
        procedure = _resolve_unique_procedure(command_call, self.workspace_index)
        if procedure is None:
            return

        procedure_path = source_id_to_path(procedure.uri)
        if procedure_path is None:
            return

        metadata_command = _metadata_command_effects(self.metadata_registry).get(
            (procedure_path.name, normalize_command_name(procedure.qualified_name))
        )
        if metadata_command is None:
            return

        for annotation in metadata_command.annotations:
            if isinstance(annotation, MetadataContext) and annotation.context_name == 'tcl':
                script_texts = _selected_argument_texts(
                    command_call,
                    selector=annotation.body_selector,
                    options=metadata_command.options,
                )
                if script_texts is None:
                    continue
                for script_text in script_texts:
                    nested_facts = _extract_embedded_script(
                        script_text,
                        self.source_path,
                        metadata_registry=self.metadata_registry,
                    )
                    self.scan_facts(nested_facts)
                continue

            if isinstance(annotation, MetadataSource):
                source_texts = _selected_argument_texts(
                    command_call,
                    selector=annotation.selector,
                    options=metadata_command.options,
                )
                if source_texts is None:
                    continue
                base_directory = _effect_base_directory(
                    annotation.base,
                    call_source_path=self.source_path,
                    procedure_path=procedure_path,
                )
                for source_text in source_texts:
                    self.source_uris.setdefault(
                        (base_directory / source_text).resolve(strict=False).as_uri(),
                        None,
                    )
                continue

            if isinstance(annotation, MetadataPackage):
                if annotation.literal_package is not None:
                    self.required_packages.add(annotation.literal_package)
                    continue
                if annotation.selector is None:
                    continue
                package_names = _selected_argument_texts(
                    command_call,
                    selector=annotation.selector,
                    options=metadata_command.options,
                )
                if package_names is None:
                    continue
                for package_name in package_names:
                    self.required_packages.add(package_name)
                continue


def _resolve_unique_procedure(
    command_call: CommandCall,
    workspace_index: WorkspaceIndex,
) -> ProcDecl | None:
    if command_call.dynamic or command_call.name is None:
        return None

    matches = workspace_index.resolve_procedure(command_call.name, command_call.namespace)
    if not matches:
        matches = workspace_index.resolve_imported_procedure(
            command_call.name,
            command_call.namespace,
        )
    if len(matches) != 1:
        return None
    return matches[0]


def _selected_argument_texts(
    command_call: CommandCall,
    *,
    selector: MetadataSelector,
    options: tuple[MetadataOption, ...],
) -> tuple[str, ...] | None:
    selected_indices = select_argument_indices(
        selector,
        command_call.arg_texts,
        options,
        command_call.arg_expanded,
    )
    if selected_indices is None:
        return None

    selected_texts: list[str] = []
    for index in selected_indices:
        if index >= len(command_call.arg_texts):
            continue
        argument_text = command_call.arg_texts[index]
        if argument_text is None:
            return None
        selected_texts.append(argument_text)
    return tuple(selected_texts)


def _extract_embedded_script(
    text: str,
    source_path: Path,
    *,
    metadata_registry: MetadataRegistry,
) -> DocumentFacts:
    parser, extractor = _embedded_script_services(metadata_registry)
    parse_result = parser.parse_document(source_path.as_uri(), text)
    return extractor.extract(parse_result, include_parse_result=False)


def _effect_base_directory(
    base: SourceBase,
    *,
    call_source_path: Path,
    procedure_path: Path,
) -> Path:
    if base == 'caller':
        return call_source_path.parent
    return procedure_path.parent.parent
