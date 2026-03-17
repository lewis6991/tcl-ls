from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from tcl_lsp.analysis.facts import FactExtractor
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    MetadataOption,
    MetadataPackage,
    MetadataSelector,
    MetadataScriptBody,
    MetadataSource,
    SourceBase,
    all_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.analysis.model import CommandCall, DocumentFacts, ProcDecl
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.parser import Parser
from tcl_lsp.workspace import source_id_to_path


@dataclass(frozen=True, slots=True)
class MetadataDependencyOverlay:
    source_uris: tuple[str, ...]
    required_packages: frozenset[str]


def metadata_dependency_overlay(
    source_path: Path,
    facts: DocumentFacts,
    workspace_index: WorkspaceIndex,
) -> MetadataDependencyOverlay:
    scanner = _DependencyScanner(
        source_path=source_path,
        workspace_index=workspace_index,
    )
    scanner.scan_facts(facts)
    return MetadataDependencyOverlay(
        source_uris=tuple(scanner.source_uris),
        required_packages=frozenset(scanner.required_packages),
    )


@metadata_lru_cache(maxsize=1)
def _candidate_effect_command_names() -> frozenset[str]:
    candidates: set[str] = set()
    for _, metadata_command in _metadata_command_effects().items():
        tail = metadata_command.name.rsplit('::', 1)[-1]
        candidates.add(tail)
        candidates.add(metadata_command.name)
    return frozenset(candidates)


@metadata_lru_cache(maxsize=1)
def _metadata_command_effects() -> dict[tuple[str, str], MetadataCommand]:
    effects_by_key: dict[tuple[str, str], MetadataCommand] = {}
    for metadata_command in all_metadata_commands():
        if metadata_command.context_name is not None:
            continue
        if not any(
            isinstance(annotation, (MetadataPackage, MetadataScriptBody, MetadataSource))
            for annotation in metadata_command.annotations
        ):
            continue
        key = (metadata_command.metadata_path.name, metadata_command.name)
        existing = effects_by_key.get(key)
        if existing is not None and (
            existing.options != metadata_command.options
            or existing.annotations != metadata_command.annotations
        ):
            raise RuntimeError(
                f'Conflicting metadata effects for `{metadata_command.name}` in '
                f'`{metadata_command.metadata_path.name}`.'
            )
        effects_by_key[key] = metadata_command

    if not effects_by_key:
        raise RuntimeError('No metadata effect entries were loaded.')
    return effects_by_key


@lru_cache(maxsize=1)
def _embedded_script_services() -> tuple[Parser, FactExtractor]:
    parser = Parser()
    return parser, FactExtractor(parser)


@dataclass(slots=True)
class _DependencyScanner:
    source_path: Path
    workspace_index: WorkspaceIndex
    source_uris: dict[str, None] = field(init=False, default_factory=dict)
    required_packages: set[str] = field(init=False, default_factory=set)

    def scan_facts(self, facts: DocumentFacts) -> None:
        candidate_names = _candidate_effect_command_names()
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

        metadata_command = _metadata_command_effects().get(
            (procedure_path.name, procedure.qualified_name)
        )
        if metadata_command is None:
            return

        for annotation in metadata_command.annotations:
            if isinstance(annotation, MetadataScriptBody):
                script_texts = _selected_argument_texts(
                    command_call,
                    selector=annotation.selector,
                    options=metadata_command.options,
                )
                if script_texts is None:
                    continue
                for script_text in script_texts:
                    nested_facts = _extract_embedded_script(script_text, self.source_path)
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


def _extract_embedded_script(text: str, source_path: Path) -> DocumentFacts:
    parser, extractor = _embedded_script_services()
    parse_result = parser.parse_document(source_path.as_uri(), text)
    return extractor.extract(parse_result, include_parse_result=False)


def _effect_base_directory(
    base: SourceBase,
    *,
    call_source_path: Path,
    procedure_path: Path,
) -> Path:
    if base == 'call-source-directory':
        return call_source_path.parent
    return procedure_path.parent.parent
