from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from tcl_lsp.analysis.facts import FactExtractor
from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.model import CommandCall, DocumentFacts, ProcDecl
from tcl_lsp.common import Position
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.workspace import source_id_to_path

_DATA_DIR = Path(__file__).resolve().parents[1] / 'data'
_EFFECTS_METADATA_PATH = _DATA_DIR / 'helper_command_effects.tcl'

type SourceBase = Literal['call-source-directory', 'proc-source-parent']


@dataclass(frozen=True, slots=True)
class MetadataDependencyOverlay:
    source_uris: tuple[str, ...]
    required_packages: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ScriptBodyEffect:
    argument_index: int


@dataclass(frozen=True, slots=True)
class _SourceEffect:
    argument_index: int
    base: SourceBase


@dataclass(frozen=True, slots=True)
class _PackageEffect:
    argument_index: int | None
    literal_package: str | None


type _CommandEffect = _ScriptBodyEffect | _SourceEffect | _PackageEffect


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


@lru_cache(maxsize=1)
def _candidate_effect_command_names() -> frozenset[str]:
    candidates: set[str] = set()
    for _, qualified_name in _helper_command_effects():
        tail = qualified_name.rsplit('::', 1)[-1]
        candidates.add(tail)
        candidates.add(qualified_name)
    return frozenset(candidates)


@lru_cache(maxsize=1)
def _helper_command_effects() -> dict[tuple[str, str], tuple[_CommandEffect, ...]]:
    metadata_uri = _EFFECTS_METADATA_PATH.as_uri()
    text = _EFFECTS_METADATA_PATH.read_text(encoding='utf-8')
    parser = Parser()
    parse_result = parser.parse_document(path=metadata_uri, text=text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid helper command metadata: {message}')

    effects_by_key: dict[tuple[str, str], list[_CommandEffect]] = {}
    for command in parse_result.script.commands:
        if word_static_text(command.words[0]) != 'meta':
            continue
        if len(command.words) != 4:
            raise RuntimeError(
                'Helper command metadata entries must be `meta effect source {spec}`.'
            )

        metadata_kind = word_static_text(command.words[1])
        source_name = word_static_text(command.words[2])
        spec = word_static_text(command.words[3])
        if metadata_kind != 'effect' or source_name is None or spec is None:
            raise RuntimeError(
                'Helper command metadata entries must be fully static `meta effect source {spec}`.'
            )

        qualified_name, effect = _parse_effect_spec(spec)
        effects_by_key.setdefault((source_name, qualified_name), []).append(effect)

    if not effects_by_key:
        raise RuntimeError('No helper command metadata entries were loaded.')

    return {
        key: tuple(effects)
        for key, effects in effects_by_key.items()
    }


def _parse_effect_spec(spec: str) -> tuple[str, _CommandEffect]:
    items = split_tcl_list(spec, Position(line=0, character=0, offset=0))
    if len(items) < 3:
        raise RuntimeError('Helper command effect metadata must include a proc name and effect.')

    proc_name = items[0].text
    effect_kind = items[1].text
    if not proc_name.startswith('::'):
        raise RuntimeError('Helper command effects must target fully qualified procedure names.')

    if effect_kind == 'script-body':
        if len(items) != 3:
            raise RuntimeError('Script-body effects must be `proc script-body argIndex`.')
        return proc_name, _ScriptBodyEffect(argument_index=_parse_argument_index(items[2].text))

    if effect_kind == 'source':
        if len(items) != 4:
            raise RuntimeError('Source effects must be `proc source argIndex base`.')
        return proc_name, _SourceEffect(
            argument_index=_parse_argument_index(items[2].text),
            base=_parse_source_base(items[3].text),
        )

    if effect_kind == 'package':
        if len(items) != 3:
            raise RuntimeError('Package effects must be `proc package packageNameOrArgIndex`.')
        package_spec = items[2].text
        if package_spec.isdigit():
            return proc_name, _PackageEffect(
                argument_index=_parse_argument_index(package_spec),
                literal_package=None,
            )
        return proc_name, _PackageEffect(argument_index=None, literal_package=package_spec)

    raise RuntimeError(f'Unknown helper command effect kind `{effect_kind}`.')


def _parse_argument_index(text: str) -> int:
    if not text.isdigit() or text == '0':
        raise RuntimeError(f'Argument indices must be positive integers, got `{text}`.')
    return int(text) - 1


def _parse_source_base(text: str) -> SourceBase:
    if text not in {'call-source-directory', 'proc-source-parent'}:
        raise RuntimeError(f'Unknown helper command source base `{text}`.')
    return text


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

        effects = _helper_command_effects().get((procedure_path.name, procedure.qualified_name), ())
        for effect in effects:
            if isinstance(effect, _ScriptBodyEffect):
                script_text = _argument_text(command_call, effect.argument_index)
                if script_text is None:
                    continue
                nested_facts = _extract_embedded_script(script_text, self.source_path)
                self.scan_facts(nested_facts)
                continue

            if isinstance(effect, _SourceEffect):
                source_text = _argument_text(command_call, effect.argument_index)
                if source_text is None:
                    continue
                base_directory = _effect_base_directory(
                    effect.base,
                    call_source_path=self.source_path,
                    procedure_path=procedure_path,
                )
                self.source_uris.setdefault(
                    (base_directory / source_text).resolve(strict=False).as_uri(),
                    None,
                )
                continue

            if isinstance(effect, _PackageEffect):
                package_name = effect.literal_package
                if package_name is None and effect.argument_index is not None:
                    package_name = _argument_text(command_call, effect.argument_index)
                if package_name:
                    self.required_packages.add(package_name)


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


def _argument_text(command_call: CommandCall, argument_index: int) -> str | None:
    if argument_index < 0 or argument_index >= len(command_call.arg_texts):
        return None
    return command_call.arg_texts[argument_index]


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
