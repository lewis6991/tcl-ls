from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from tcl_lsp.analysis.facts.utils import normalize_command_name
from tcl_lsp.analysis.model import BINDING_KINDS, BindingKind
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Span
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataRegistry,
    metadata_lookup_names,
)
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import BareWord, BracedWord, Command, Token, Word

_MISSING = object()
_META_MODULE_PREFIX = 'meta module '
_SIMPLE_META_MODULE_BRACED_RE = re.compile(r'^\{([^{}]*)\}$')
_SIMPLE_META_MODULE_QUOTED_RE = re.compile(r'^"([^"\\]*)"$')

type SourceBase = Literal['caller', 'definition']
type MetadataOptionKind = Literal['flag', 'value', 'stop']
type OptionScanState = Literal[
    'ok', 'dynamic', 'unstable', 'unknown-option', 'missing-option-value'
]


@dataclass(frozen=True, slots=True)
class MetadataSelector:
    start_index: int
    all_remaining: bool
    list_mode: bool
    after_options: bool
    step: int = 1
    start_from_end: bool = False
    end_index: int | None = None
    end_from_end: bool = False

    @property
    def has_relative_bounds(self) -> bool:
        return self.start_from_end or self.end_from_end

    @property
    def selects_single_argument(self) -> bool:
        return not self.all_remaining and self.end_index is None and self.step == 1


@dataclass(frozen=True, slots=True)
class MetadataOption:
    name: str
    kind: MetadataOptionKind


@dataclass(frozen=True, slots=True)
class OptionScanResult:
    state: OptionScanState
    positional_indices: tuple[int, ...]
    option_index: int | None = None
    option_name: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataBind:
    selector: MetadataSelector
    kind: BindingKind | None


@dataclass(frozen=True, slots=True)
class MetadataRef:
    selector: MetadataSelector


@dataclass(frozen=True, slots=True)
class MetadataSource:
    selector: MetadataSelector
    base: SourceBase


@dataclass(frozen=True, slots=True)
class MetadataPackage:
    selector: MetadataSelector | None
    literal_package: str | None


@dataclass(frozen=True, slots=True)
class MetadataContext:
    body_selector: MetadataSelector
    context_name: str
    owner_selector: MetadataSelector | None


@dataclass(frozen=True, slots=True)
class MetadataProcedure:
    member_name_selector: MetadataSelector | None
    member_name_literal: str | None
    parameter_selector: MetadataSelector | None
    parameter_literal: str | None
    body_selector: MetadataSelector | None
    body_context: str | None


@dataclass(frozen=True, slots=True)
class MetadataPlugin:
    script_path: Path
    proc_name: str


type MetadataAnnotation = (
    MetadataBind
    | MetadataRef
    | MetadataSource
    | MetadataPackage
    | MetadataContext
    | MetadataProcedure
    | MetadataPlugin
)


@dataclass(frozen=True, slots=True)
class MetadataCommand:
    metadata_path: Path
    uri: str
    name: str
    context_name: str | None
    context_extends: str | None
    signature: str
    documentation: str | None
    name_span: Span
    options: tuple[MetadataOption, ...]
    subcommands: tuple[str, ...]
    annotations: tuple[MetadataAnnotation, ...]


@dataclass(frozen=True, slots=True)
class MetadataFileSummary:
    module_name: str | None
    module_declaration_count: int
    commands: tuple[MetadataCommand, ...]
    language_extends: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class MetadataFileModuleInfo:
    module_name: str | None
    module_declaration_count: int


def load_metadata_commands(metadata_path: Path) -> tuple[MetadataCommand, ...]:
    return metadata_file_summary(metadata_path).commands


def metadata_file_module_info(metadata_path: Path) -> MetadataFileModuleInfo:
    return _metadata_file_module_info(metadata_path)


def metadata_file_summary(metadata_path: Path) -> MetadataFileSummary:
    return _metadata_file_summary(metadata_path)


@metadata_lru_cache(maxsize=None)
def _metadata_file_module_info(
    metadata_path: Path,
) -> MetadataFileModuleInfo:
    text = metadata_path.read_text(encoding='utf-8')
    module_name: str | None = None
    module_declaration_count = 0
    needs_parser_fallback = False
    # Cold startup only needs the declared module/package name. Most metadata
    # files use a simple literal `meta module ...` header, so avoid a full Tcl
    # parse unless the header uses a more complex form.
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if not stripped.startswith(_META_MODULE_PREFIX):
            continue
        declared_module_name = _simple_meta_module_name(stripped[len(_META_MODULE_PREFIX) :])
        if declared_module_name is None:
            needs_parser_fallback = True
            break
        if module_name is None:
            module_name = declared_module_name
        module_declaration_count += 1

    if needs_parser_fallback:
        metadata_uri = metadata_path.as_uri()
        parse_result = Parser().parse_document(path=metadata_uri, text=text)
        if parse_result.diagnostics:
            message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
            raise RuntimeError(f'Invalid metadata file `{metadata_path.name}`: {message}')

        module_name = None
        module_declaration_count = 0
        for command in parse_result.script.commands:
            if len(command.words) < 2:
                continue
            if word_static_text(command.words[0]) != 'meta':
                continue
            if word_static_text(command.words[1]) != 'module':
                continue
            declared_module_name = (
                word_static_text(command.words[2]) if len(command.words) == 3 else None
            )
            if declared_module_name is None:
                raise RuntimeError('Metadata module entries must be `meta module name`.')
            if module_name is None:
                module_name = declared_module_name
            module_declaration_count += 1

    return MetadataFileModuleInfo(
        module_name=module_name,
        module_declaration_count=module_declaration_count,
    )


def _simple_meta_module_name(text: str) -> str | None:
    if not text:
        return None
    braced_match = _SIMPLE_META_MODULE_BRACED_RE.fullmatch(text)
    if braced_match is not None:
        return braced_match.group(1)
    quoted_match = _SIMPLE_META_MODULE_QUOTED_RE.fullmatch(text)
    if quoted_match is not None:
        return quoted_match.group(1)
    if any(character.isspace() or character in '${}[];"\\' for character in text):
        return None
    return text


@metadata_lru_cache(maxsize=None)
def _metadata_file_summary(
    metadata_path: Path,
) -> MetadataFileSummary:
    metadata_uri = metadata_path.as_uri()
    text = metadata_path.read_text(encoding='utf-8')
    parse_result = Parser().parse_document(path=metadata_uri, text=text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata file `{metadata_path.name}`: {message}')

    module_name: str | None = None
    module_declaration_count = 0
    commands: list[MetadataCommand] = []
    language_extends: list[tuple[str, bool]] = []
    for command in parse_result.script.commands:
        if not command.words:
            continue
        if word_static_text(command.words[0]) != 'meta':
            raise RuntimeError(
                'Metadata top-level entries must be `meta module name`, '
                '`meta command name {args}`, `meta command name variants { ... }`, '
                'or `meta language name { ... }`.'
            )
        if len(command.words) < 2:
            raise RuntimeError(
                'Metadata top-level entries must be `meta module name`, '
                '`meta command name {args}`, `meta command name variants { ... }`, '
                'or `meta language name { ... }`.'
            )
        entry_kind = word_static_text(command.words[1])
        if entry_kind == 'module':
            declared_module_name = (
                word_static_text(command.words[2]) if len(command.words) == 3 else None
            )
            if declared_module_name is None:
                raise RuntimeError('Metadata module entries must be `meta module name`.')
            if module_name is None:
                module_name = declared_module_name
            module_declaration_count += 1
            continue
        if entry_kind == 'command':
            commands.extend(
                _parse_metadata_command_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                )
            )
            continue
        if entry_kind == 'language':
            context_name, context_extends, context_commands = _parse_metadata_context_entry(
                command,
                metadata_path=metadata_path,
                metadata_uri=metadata_uri,
            )
            language_extends.append((context_name, context_extends == 'tcl'))
            commands.extend(context_commands)
            continue
        raise RuntimeError(
            'Metadata top-level entries must be `meta module name`, '
            '`meta command name {args}`, `meta command name variants { ... }`, '
            'or `meta language name { ... }`.'
        )

    metadata_commands = tuple(commands)
    if metadata_commands:
        metadata_commands = _commands_with_derived_subcommands(metadata_commands)
    return MetadataFileSummary(
        module_name=module_name,
        module_declaration_count=module_declaration_count,
        commands=metadata_commands,
        language_extends=tuple(language_extends),
    )


def all_metadata_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[MetadataCommand, ...]:
    return _all_metadata_commands(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _all_metadata_commands(metadata_registry: MetadataRegistry) -> tuple[MetadataCommand, ...]:
    commands: list[MetadataCommand] = []
    for metadata_path in metadata_registry.metadata_files():
        commands.extend(load_metadata_commands(metadata_path))
    return tuple(commands)


@metadata_lru_cache(maxsize=1)
def all_metadata_language_extends(metadata_registry: MetadataRegistry) -> dict[str, bool]:
    language_extends: dict[str, bool] = {}
    for _, layer_paths in metadata_registry.metadata_file_layers():
        layer_extends: dict[str, bool] = {}
        for metadata_path in layer_paths:
            for language_name, extends_tcl in metadata_file_summary(metadata_path).language_extends:
                # Repeated `meta language name { ... }` blocks compose within
                # one metadata root, so any extending block keeps the language
                # open inside that layer.
                layer_extends[language_name] = (
                    layer_extends.get(language_name, False) or extends_tcl
                )
        # Later metadata roots override earlier roots, including whether a
        # language stays open to Tcl fallback.
        language_extends.update(layer_extends)
    return language_extends


def file_scoped_annotated_metadata_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[tuple[str, str], MetadataCommand]:
    return _file_scoped_annotated_metadata_commands(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _file_scoped_annotated_metadata_commands(
    metadata_registry: MetadataRegistry,
) -> dict[tuple[str, str], MetadataCommand]:
    commands_by_lookup_name: dict[str, dict[str, MetadataCommand]] = {}
    for _, layer_paths in metadata_registry.metadata_file_layers():
        layer_overrides_by_lookup_name: dict[str, dict[str, None]] = {}
        layer_commands_by_lookup_name: dict[str, dict[str, MetadataCommand]] = {}
        for metadata_path in layer_paths:
            override_names, annotated_commands = _file_scoped_annotated_entries_for_file(
                metadata_path
            )
            if not override_names:
                continue
            for lookup_name in metadata_lookup_names(metadata_path):
                layer_override_names = layer_overrides_by_lookup_name.setdefault(lookup_name, {})
                layer_commands = layer_commands_by_lookup_name.setdefault(lookup_name, {})
                for command_name in override_names:
                    if command_name in layer_override_names:
                        raise RuntimeError(
                            f'Conflicting file-scoped metadata annotations for '
                            f'`{command_name}` in `{metadata_path.name}`.'
                        )
                    layer_override_names[command_name] = None
                for command_name, metadata_command in annotated_commands.items():
                    existing = layer_commands.get(command_name)
                    if existing is not None and (
                        existing.options != metadata_command.options
                        or existing.subcommands != metadata_command.subcommands
                        or existing.annotations != metadata_command.annotations
                    ):
                        raise RuntimeError(
                            f'Conflicting file-scoped metadata annotations for '
                            f'`{metadata_command.name}` in `{metadata_path.name}`.'
                        )
                    layer_commands[command_name] = metadata_command

        for lookup_name, override_names in layer_overrides_by_lookup_name.items():
            commands = commands_by_lookup_name.setdefault(lookup_name, {})
            _discard_overridden_command_trees(commands, override_names)
            commands.update(layer_commands_by_lookup_name.get(lookup_name, {}))

    return {
        (lookup_name, command_name): metadata_command
        for lookup_name, commands in commands_by_lookup_name.items()
        for command_name, metadata_command in commands.items()
    }


def _file_scoped_annotated_entries_for_file(
    metadata_path: Path,
) -> tuple[tuple[str, ...], dict[str, MetadataCommand]]:
    override_entries: dict[str, MetadataCommand | None] = {}
    annotated: dict[str, MetadataCommand] = {}
    for metadata_command in load_metadata_commands(metadata_path):
        if metadata_command.context_name is not None:
            continue

        command_name = normalize_command_name(metadata_command.name)
        annotated_command = (
            metadata_command
            if (
                metadata_command.options
                or metadata_command.subcommands
                or metadata_command.annotations
            )
            else None
        )
        existing = override_entries.get(command_name, _MISSING)
        if existing is _MISSING:
            override_entries[command_name] = annotated_command
            if annotated_command is not None:
                annotated[command_name] = annotated_command
            continue

        if annotated_command is None:
            continue
        if existing is None:
            override_entries[command_name] = annotated_command
            annotated[command_name] = annotated_command
            continue
        existing_command = cast(MetadataCommand, existing)
        if (
            existing_command.options == annotated_command.options
            and existing_command.subcommands == annotated_command.subcommands
            and existing_command.annotations == annotated_command.annotations
        ):
            continue
        raise RuntimeError(
            f'Conflicting file-scoped metadata annotations for '
            f'`{metadata_command.name}` in `{metadata_path.name}`.'
        )

    return tuple(override_entries), annotated


def _discard_overridden_command_trees[CommandValue](
    commands: dict[str, CommandValue],
    override_commands: Mapping[str, object],
) -> None:
    override_names = tuple(override_commands)
    for existing_name in tuple(commands):
        if any(
            existing_name == override_name or existing_name.startswith(f'{override_name} ')
            for override_name in override_names
        ):
            commands.pop(existing_name, None)


def _parse_metadata_command_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    context_name: str | None = None,
    context_extends: str | None = None,
    parent_name: str | None = None,
) -> tuple[MetadataCommand, ...]:
    if context_name is None:
        if len(command.words) not in {4, 5}:
            raise RuntimeError(
                'Metadata command entries must be `meta command name {args}` '
                'optionally followed by an annotation body, or '
                '`meta command name variants { ... }`.'
            )
        command_name = word_static_text(command.words[2])
        name_word = command.words[2]
        declaration_word = command.words[3]
        annotation_word = command.words[4] if len(command.words) == 5 else None
    else:
        if len(command.words) not in {3, 4}:
            raise RuntimeError(
                'Metadata language command entries must be '
                '`command name {args}` optionally followed by an annotation body, '
                'or `command name variants { ... }`.'
            )
        command_name = word_static_text(command.words[1])
        name_word = command.words[1]
        declaration_word = command.words[2]
        annotation_word = command.words[3] if len(command.words) == 4 else None

    if command_name is None:
        raise RuntimeError('Metadata command entries must be fully static declarations.')
    if ' ' in command_name:
        raise RuntimeError(
            'Metadata command entries must use single command names. '
            'Use nested `command name {shape}` declarations for child commands.'
        )

    full_name = command_name if parent_name is None else f'{parent_name} {command_name}'
    documentation = _command_documentation(command.leading_comments)

    if _is_bare_keyword(declaration_word, 'variants'):
        if annotation_word is None:
            raise RuntimeError(
                f'Metadata command `{full_name}` variants must be followed by a body.'
            )
        return _load_metadata_variant_commands(
            _parse_metadata_variant_body(
                annotation_word,
                metadata_uri=metadata_uri,
                command_name=full_name,
            ),
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            name_span=name_word.content_span,
            documentation=documentation,
        )

    if annotation_word is not None and isinstance(declaration_word, BareWord):
        raise RuntimeError(
            f'Metadata command `{full_name}` must use a braced shape when a clause body is present.'
        )

    signature = word_static_text(declaration_word)
    if signature is None:
        raise RuntimeError('Metadata command entries must be fully static declarations.')
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            signature=signature,
            documentation=documentation,
            name_span=name_word.content_span,
            options=options,
            subcommands=(),
            annotations=annotations,
        ),
        *nested_commands,
    )


def _parse_metadata_context_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
) -> tuple[str, str | None, tuple[MetadataCommand, ...]]:
    if len(command.words) != 4:
        raise RuntimeError('Metadata language entries must be `meta language name { ... }`.')

    context_name = word_static_text(command.words[2])
    if context_name is None:
        raise RuntimeError('Metadata language entries must have a static language name.')

    body_text = _metadata_body_text(command.words[3])
    parse_result = Parser().parse_document(
        path=f'{metadata_uri}#context:{context_name}', text=body_text
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(
            f'Invalid metadata language `{context_name}` in `{metadata_path.name}`: {message}'
        )

    nested_command_entries: list[Command] = []
    context_extends: str | None = None
    for nested_command in parse_result.script.commands:
        nested_name = word_static_text(nested_command.words[0])
        if nested_name == 'extends':
            if context_extends is not None:
                raise RuntimeError(
                    f'Metadata language `{context_name}` declares multiple extends clauses.'
                )
            if len(nested_command.words) != 2 or word_static_text(nested_command.words[1]) != 'tcl':
                raise RuntimeError(
                    f'Metadata language `{context_name}` extends clauses must be `extends tcl`.'
                )
            context_extends = 'tcl'
            continue
        if nested_name != 'command':
            raise RuntimeError(
                f'Metadata language `{context_name}` entries must use '
                '`command name {args}`, `command name variants { ... }`, '
                'or `extends tcl`.'
            )
        nested_command_entries.append(nested_command)

    commands: list[MetadataCommand] = []
    for nested_command in nested_command_entries:
        commands.extend(
            _parse_metadata_command_entry(
                nested_command,
                metadata_path=metadata_path,
                metadata_uri=metadata_uri,
                context_name=context_name,
                context_extends=context_extends,
            )
        )

    return context_name, context_extends, tuple(commands)


def select_argument_indices(
    selector: MetadataSelector,
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...] | None = None,
) -> tuple[int, ...] | None:
    expanded_flags = _normalized_argument_expansion_flags(arg_texts, arg_expanded)
    if selector.after_options:
        scan_result = scan_command_options(arg_texts, options, expanded_flags)
        if scan_result.state == 'dynamic':
            return None
        if scan_result.state not in {'ok', 'unstable'}:
            return None
        return _select_resolved_argument_indices(
            selector,
            scan_result.positional_indices,
            unstable=scan_result.state == 'unstable',
        )

    return _select_resolved_argument_indices(
        selector,
        tuple(range(len(arg_texts))),
        unstable=False,
        expanded_flags=expanded_flags,
    )


def scan_command_options(
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...] | None = None,
) -> OptionScanResult:
    expanded_flags = _normalized_argument_expansion_flags(arg_texts, arg_expanded)
    if not options:
        return _positional_scan_result(
            start_index=0,
            arg_texts=arg_texts,
            expanded_flags=expanded_flags,
            state='ok',
        )

    option_specs = {option.name: option for option in options}
    index = 0
    while index < len(arg_texts):
        if expanded_flags[index]:
            return OptionScanResult(state='unstable', positional_indices=())

        arg_text = arg_texts[index]
        if arg_text is None:
            return _positional_scan_result(
                start_index=index,
                arg_texts=arg_texts,
                expanded_flags=expanded_flags,
                state='dynamic',
            )

        option = option_specs.get(arg_text)
        if option is None:
            if arg_text.startswith('-') and arg_text != '-':
                return OptionScanResult(
                    state='unknown-option',
                    positional_indices=(),
                    option_index=index,
                    option_name=arg_text,
                )
            return _positional_scan_result(
                start_index=index,
                arg_texts=arg_texts,
                expanded_flags=expanded_flags,
                state='ok',
            )

        if option.kind == 'flag':
            index += 1
            continue
        if option.kind == 'value':
            if index + 1 >= len(arg_texts):
                return OptionScanResult(
                    state='missing-option-value',
                    positional_indices=(),
                    option_index=index,
                    option_name=arg_text,
                )
            if expanded_flags[index + 1]:
                return OptionScanResult(state='unstable', positional_indices=())
            index += 2
            continue
        return _positional_scan_result(
            start_index=index + 1,
            arg_texts=arg_texts,
            expanded_flags=expanded_flags,
            state='ok',
        )

    return OptionScanResult(state='ok', positional_indices=())


def _normalized_argument_expansion_flags(
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...] | None,
) -> tuple[bool, ...]:
    if arg_expanded is None:
        return (False,) * len(arg_texts)
    if len(arg_expanded) >= len(arg_texts):
        return arg_expanded[: len(arg_texts)]
    return arg_expanded + (False,) * (len(arg_texts) - len(arg_expanded))


def _positional_scan_result(
    *,
    start_index: int,
    arg_texts: tuple[str | None, ...],
    expanded_flags: tuple[bool, ...],
    state: Literal['ok', 'dynamic'],
) -> OptionScanResult:
    first_expanded_index = _first_expanded_index(expanded_flags, start_index)
    if first_expanded_index is None:
        return OptionScanResult(
            state=state,
            positional_indices=tuple(range(start_index, len(arg_texts))),
        )
    return OptionScanResult(
        state='unstable',
        positional_indices=tuple(range(start_index, first_expanded_index)),
    )


def _first_expanded_index(
    expanded_flags: tuple[bool, ...],
    start_index: int = 0,
) -> int | None:
    for index in range(start_index, len(expanded_flags)):
        if expanded_flags[index]:
            return index
    return None


def _parse_annotation_body(
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    body_text: str,
) -> tuple[tuple[MetadataOption, ...], tuple[MetadataAnnotation, ...], tuple[MetadataCommand, ...]]:
    annotation_uri = f'{metadata_uri}#{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=body_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata command annotations for `{command_name}`: {message}')

    options: list[MetadataOption] = []
    annotations: list[MetadataAnnotation] = []
    nested_commands: list[MetadataCommand] = []
    for command in parse_result.script.commands:
        annotation_name = word_static_text(command.words[0])
        if annotation_name is None:
            raise RuntimeError(
                f'Metadata command annotations for `{command_name}` must be static commands.'
            )

        if annotation_name == 'option':
            options.append(_parse_option_annotation(command, command_name))
            continue
        if annotation_name == 'command':
            nested_commands.extend(
                _parse_nested_command_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    parent_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                )
            )
            continue
        if annotation_name == 'bind':
            annotations.append(_parse_bind_annotation(command, command_name))
            continue
        if annotation_name == 'ref':
            annotations.append(_parse_ref_annotation(command, command_name))
            continue
        if annotation_name == 'enter':
            annotations.append(_parse_enter_annotation(command, command_name))
            continue
        if annotation_name == 'source':
            annotations.append(_parse_source_annotation(command, command_name))
            continue
        if annotation_name == 'package':
            annotations.append(_parse_package_annotation(command, command_name))
            continue
        if annotation_name == 'procedure':
            annotations.append(_parse_procedure_annotation(command, command_name))
            continue
        if annotation_name == 'plugin':
            annotations.append(
                _parse_plugin_annotation(
                    command,
                    command_name,
                    metadata_path=metadata_path,
                )
            )
            continue
        raise RuntimeError(
            f'Unknown metadata command annotation `{annotation_name}` for `{command_name}`.'
        )

    return tuple(options), tuple(annotations), tuple(nested_commands)


def _parse_option_annotation(command: Command, command_name: str) -> MetadataOption:
    words = _annotation_words(command, command_name)
    if len(words) == 2:
        return MetadataOption(name=words[1], kind='flag')
    if len(words) == 3 and words[2] == 'value':
        return MetadataOption(name=words[1], kind='value')
    if len(words) == 3 and words[1] == '--' and words[2] == 'stop':
        return MetadataOption(name='--', kind='stop')
    raise RuntimeError(
        f'Option annotations for `{command_name}` must be `option name`, '
        '`option name value`, or `option -- stop`.'
    )


def _parse_nested_command_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    parent_name: str,
    context_name: str | None,
    context_extends: str | None,
) -> tuple[MetadataCommand, ...]:
    if len(command.words) not in {3, 4}:
        raise RuntimeError(
            f'Nested command declarations for `{parent_name}` must be '
            '`command name {shape}` optionally followed by an annotation body, '
            'or `command name variants { ... }`.'
        )

    command_name = word_static_text(command.words[1])
    if command_name is None:
        raise RuntimeError(f'Nested command declarations for `{parent_name}` must be fully static.')
    if ' ' in command_name:
        raise RuntimeError(
            f'Nested command declarations for `{parent_name}` must use single command names.'
        )

    full_name = f'{parent_name} {command_name}'
    declaration_word = command.words[2]
    annotation_word = command.words[3] if len(command.words) == 4 else None

    if _is_bare_keyword(declaration_word, 'variants'):
        if annotation_word is None:
            raise RuntimeError(
                f'Nested command variants for `{full_name}` must be followed by a body.'
            )
        return _load_metadata_variant_commands(
            _parse_metadata_variant_body(
                annotation_word,
                metadata_uri=metadata_uri,
                command_name=full_name,
            ),
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            name_span=command.words[1].content_span,
            documentation=_command_documentation(command.leading_comments),
        )

    if annotation_word is not None and isinstance(declaration_word, BareWord):
        raise RuntimeError(
            f'Nested command `{full_name}` must use a braced shape when a clause body is present.'
        )

    signature = word_static_text(declaration_word)
    if signature is None:
        raise RuntimeError(f'Nested command declarations for `{parent_name}` must be fully static.')

    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            signature=signature,
            documentation=_command_documentation(command.leading_comments),
            name_span=command.words[1].content_span,
            options=options,
            subcommands=(),
            annotations=annotations,
        ),
        *nested_commands,
    )


def _parse_bind_annotation(command: Command, command_name: str) -> MetadataBind:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    kind: BindingKind | None = None
    if consumed < len(words) - 1:
        if consumed != len(words) - 2:
            raise RuntimeError(
                f'Bind annotations for `{command_name}` must be '
                '`bind selector` or `bind selector kind`.'
            )
        kind = _parse_binding_kind(words[-1], command_name)
    elif _implicit_binding_kind(command_name) is None:
        raise RuntimeError(f'Metadata command `{command_name}` requires an explicit binding kind.')
    return MetadataBind(selector=selector, kind=kind)


def _parse_ref_annotation(command: Command, command_name: str) -> MetadataRef:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    if consumed != len(words) - 1:
        raise RuntimeError(f'Ref annotations for `{command_name}` must be `ref selector`.')
    return MetadataRef(selector=selector)


def _parse_source_annotation(command: Command, command_name: str) -> MetadataSource:
    words = _annotation_words(command, command_name)
    if len(words) < 3:
        raise RuntimeError(
            f'Source annotations for `{command_name}` must be `source selector base`.'
        )
    selector, consumed = _parse_selector_tokens(words[1:-1], command_name=command_name)
    if consumed != len(words) - 2:
        raise RuntimeError(
            f'Source annotations for `{command_name}` must be `source selector base`.'
        )
    return MetadataSource(selector=selector, base=_parse_source_base(words[-1]))


def _parse_package_annotation(command: Command, command_name: str) -> MetadataPackage:
    words = _annotation_words(command, command_name)
    if len(words) == 3 and words[1] == 'literal':
        return MetadataPackage(selector=None, literal_package=words[2])
    if len(words) >= 3 and words[1] == 'select':
        selector, consumed = _parse_selector_tokens(words[2:], command_name=command_name)
        if consumed != len(words) - 2:
            raise RuntimeError(
                f'Package annotations for `{command_name}` must be `package literal name` '
                'or `package select selector`.'
            )
        _validate_package_selector(selector, command_name)
        return MetadataPackage(selector=selector, literal_package=None)
    raise RuntimeError(
        f'Package annotations for `{command_name}` must be `package literal name` '
        'or `package select selector`.'
    )


def _parse_enter_annotation(command: Command, command_name: str) -> MetadataContext:
    words = _annotation_words(command, command_name)
    if len(words) < 4 or words[2] != 'body':
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must be '
            '`enter language body selector` or '
            '`enter language body selector owner selector`.'
        )

    context_name = words[1]
    body_selector, consumed = _parse_selector_tokens(words[3:], command_name=command_name)
    owner_selector: MetadataSelector | None = None
    index = 3 + consumed
    if index < len(words):
        if words[index] != 'owner':
            raise RuntimeError(
                f'Enter annotations for `{command_name}` must be '
                '`enter language body selector` or '
                '`enter language body selector owner selector`.'
            )
        owner_selector, owner_consumed = _parse_selector_tokens(
            words[index + 1 :],
            command_name=command_name,
        )
        if owner_consumed != len(words) - index - 1:
            raise RuntimeError(
                f'Enter annotations for `{command_name}` must be '
                '`enter language body selector` or '
                '`enter language body selector owner selector`.'
            )
        _validate_context_owner_selector(owner_selector, command_name)
    _validate_context_body_selector(body_selector, command_name)
    return MetadataContext(
        body_selector=body_selector,
        context_name=context_name,
        owner_selector=owner_selector,
    )


def _parse_procedure_annotation(command: Command, command_name: str) -> MetadataProcedure:
    if len(command.words) != 2:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must be '
            'a `procedure { ... }` block with `name ...` and `params ...`, '
            'plus optional `body select selector` and `language body-language`.'
        )

    config_text = _metadata_body_text(command.words[1])
    annotation_uri = f'procedure:{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=config_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid procedure annotation for `{command_name}`: {message}')

    member_name_selector: MetadataSelector | None | object = _MISSING
    member_name_literal: str | None | object = _MISSING
    parameter_selector: MetadataSelector | None | object = _MISSING
    parameter_literal: str | None | object = _MISSING
    body_selector: MetadataSelector | None = None
    body_context: str | None = None

    for nested_command in parse_result.script.commands:
        nested_words = _annotation_words(nested_command, command_name)
        nested_name = nested_words[0]
        if nested_name == 'name':
            if member_name_selector is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `name`.'
                )
            member_name_selector, member_name_literal = _parse_procedure_value(
                nested_words[1:],
                command_name=command_name,
                role='name',
                allow_literal=True,
                allow_none=True,
            )
            continue
        if nested_name == 'params':
            if parameter_selector is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `params`.'
                )
            parameter_selector, parameter_literal = _parse_procedure_value(
                nested_words[1:],
                command_name=command_name,
                role='params',
                allow_literal=True,
                allow_none=True,
            )
            continue
        if nested_name == 'body':
            if body_selector is not None:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `body`.'
                )
            body_selector, body_literal = _parse_procedure_value(
                nested_words[1:],
                command_name=command_name,
                role='body',
                allow_literal=False,
                allow_none=False,
            )
            if body_literal is not None:
                raise RuntimeError(
                    f'Procedure body selectors for `{command_name}` must use `body select selector`.'
                )
            continue
        if nested_name == 'language':
            if body_context is not None:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `language`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure body languages for `{command_name}` must be `language name`.'
                )
            body_context = nested_words[1]
            continue
        raise RuntimeError(f'Unknown procedure setting `{nested_name}` for `{command_name}`.')

    if member_name_selector is _MISSING or parameter_selector is _MISSING:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must declare `name` and `params`.'
        )
    if body_context is not None and body_selector is None:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` may only declare `language` '
            'when `body` is present.'
        )

    return MetadataProcedure(
        member_name_selector=cast(MetadataSelector | None, member_name_selector),
        member_name_literal=cast(str | None, member_name_literal),
        parameter_selector=cast(MetadataSelector | None, parameter_selector),
        parameter_literal=cast(str | None, parameter_literal),
        body_selector=body_selector,
        body_context=body_context,
    )


def _parse_plugin_annotation(
    command: Command,
    command_name: str,
    *,
    metadata_path: Path,
) -> MetadataPlugin:
    words = _annotation_words(command, command_name)
    if len(words) != 3:
        raise RuntimeError(
            f'Plugin annotations for `{command_name}` must be `plugin scriptPath procName`.'
        )

    script_path = Path(words[1])
    if not script_path.is_absolute():
        script_path = metadata_path.parent / script_path
    script_path = script_path.resolve(strict=False)
    if not script_path.is_file():
        raise RuntimeError(
            f'Plugin annotation for `{command_name}` references missing script `{words[1]}`.'
        )

    return MetadataPlugin(script_path=script_path, proc_name=words[2])


def _validate_package_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or not selector.selects_single_argument:
        raise RuntimeError(
            f'Package annotations for `{command_name}` must select a single argument.'
        )


def _validate_context_body_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must use direct positional selectors.'
        )
    if selector.step != 1:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must select one contiguous body range.'
        )


def _validate_context_owner_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or selector.after_options or not selector.selects_single_argument:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must select exactly one owner argument.'
        )


def _parse_selector_tokens(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
) -> tuple[MetadataSelector, int]:
    index = 0
    after_options = False
    list_mode = False
    step = 1

    if index < len(words) and words[index] == 'after-options':
        after_options = True
        index += 1
    if index < len(words) and words[index] == 'list':
        list_mode = True
        index += 1
    if index >= len(words):
        raise RuntimeError(f'Metadata selector for `{command_name}` is missing an index.')

    start_index, start_from_end, all_remaining, end_index, end_from_end = _parse_selector_range(
        words[index],
        command_name=command_name,
    )
    index += 1

    if index < len(words) and words[index] == 'step':
        if index + 1 >= len(words):
            raise RuntimeError(f'Metadata selector for `{command_name}` must be `selector step N`.')
        step_text = words[index + 1]
        if not step_text.isdigit() or step_text == '0':
            raise RuntimeError(f'Metadata selector for `{command_name}` must use a positive step.')
        step = int(step_text)
        index += 2

    if step != 1 and not (all_remaining or end_index is not None):
        raise RuntimeError(
            f'Metadata selector for `{command_name}` requires a range before `step`.'
        )

    return (
        MetadataSelector(
            start_index=start_index,
            all_remaining=all_remaining,
            list_mode=list_mode,
            after_options=after_options,
            step=step,
            start_from_end=start_from_end,
            end_index=end_index,
            end_from_end=end_from_end,
        ),
        index,
    )


def parse_selector_tokens(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
) -> tuple[MetadataSelector, int]:
    return _parse_selector_tokens(words, command_name=command_name)


def validate_context_body_selector(selector: MetadataSelector, command_name: str) -> None:
    _validate_context_body_selector(selector, command_name)


def validate_context_owner_selector(selector: MetadataSelector, command_name: str) -> None:
    _validate_context_owner_selector(selector, command_name)


def validate_procedure_selector(
    selector: MetadataSelector,
    *,
    command_name: str,
    role: str,
) -> None:
    _validate_procedure_selector(selector, command_name=command_name, role=role)


def _select_resolved_argument_indices(
    selector: MetadataSelector,
    resolved_indices: tuple[int, ...],
    *,
    unstable: bool,
    expanded_flags: tuple[bool, ...] | None = None,
) -> tuple[int, ...] | None:
    if not resolved_indices and unstable:
        return None

    effective_end = _effective_selector_end(selector, len(resolved_indices))
    if effective_end is None:
        if unstable:
            return None
    else:
        if unstable and effective_end >= len(resolved_indices):
            return None
        if expanded_flags is not None and _selector_is_unstable(
            selector,
            expanded_flags=expanded_flags,
            resolved_count=len(resolved_indices),
            effective_end=effective_end,
        ):
            return None

    start_index = _resolve_selector_endpoint(
        selector.start_index,
        from_end=selector.start_from_end,
        resolved_count=len(resolved_indices),
    )
    if start_index < 0:
        start_index = 0
    if start_index >= len(resolved_indices):
        if unstable:
            return None
        return ()

    if effective_end is None:
        stop_index = len(resolved_indices) - 1
    else:
        stop_index = min(effective_end, len(resolved_indices) - 1)

    if stop_index < start_index:
        return ()

    return tuple(
        resolved_indices[index] for index in range(start_index, stop_index + 1, selector.step)
    )


def _selector_is_unstable(
    selector: MetadataSelector,
    *,
    expanded_flags: tuple[bool, ...],
    resolved_count: int,
    effective_end: int | None,
) -> bool:
    first_expanded_index = _first_expanded_index(expanded_flags)
    if first_expanded_index is None:
        return False
    if selector.has_relative_bounds or selector.all_remaining:
        return True
    assert effective_end is not None
    return first_expanded_index <= effective_end


def _effective_selector_end(selector: MetadataSelector, resolved_count: int) -> int | None:
    if selector.all_remaining:
        return None
    if selector.end_index is None:
        return _resolve_selector_endpoint(
            selector.start_index,
            from_end=selector.start_from_end,
            resolved_count=resolved_count,
        )
    return _resolve_selector_endpoint(
        selector.end_index,
        from_end=selector.end_from_end,
        resolved_count=resolved_count,
    )


def _resolve_selector_endpoint(
    index: int,
    *,
    from_end: bool,
    resolved_count: int,
) -> int:
    if from_end:
        return resolved_count - 1 - index
    return index


def _parse_selector_range(
    token: str,
    *,
    command_name: str,
) -> tuple[int, bool, bool, int | None, bool]:
    if '..' not in token:
        start_index, start_from_end = _parse_selector_endpoint(token, command_name=command_name)
        return start_index, start_from_end, False, None, False

    start_text, end_text = token.split('..', maxsplit=1)
    start_index, start_from_end = _parse_selector_endpoint(start_text, command_name=command_name)
    if end_text == '':
        return start_index, start_from_end, True, None, False

    end_index, end_from_end = _parse_selector_endpoint(end_text, command_name=command_name)
    return start_index, start_from_end, False, end_index, end_from_end


def _parse_selector_endpoint(
    text: str,
    *,
    command_name: str,
) -> tuple[int, bool]:
    if text == '':
        raise RuntimeError(f'Metadata selector for `{command_name}` is missing an index.')
    if text == 'last':
        return 0, True
    if text.startswith('last-'):
        offset_text = text.removeprefix('last-')
        if not offset_text.isdigit() or offset_text == '0':
            raise RuntimeError(
                f'Metadata selector for `{command_name}` must use `last` or `last-N` '
                'with a positive integer.'
            )
        return int(offset_text), True
    if not text.isdigit() or text == '0':
        raise RuntimeError(
            f'Metadata selector for `{command_name}` must use a positive 1-based index, '
            '`last`, or `last-N`.'
        )
    return int(text) - 1, False


def _parse_source_base(text: str) -> SourceBase:
    if text == 'caller':
        return 'caller'
    if text == 'definition':
        return 'definition'
    raise RuntimeError(f'Unknown metadata source base `{text}`.')


def _parse_binding_kind(text: str, command_name: str) -> BindingKind:
    if text not in BINDING_KINDS:
        raise RuntimeError(f'Unknown metadata binding kind `{text}` for `{command_name}`.')
    return text


def _implicit_binding_kind(command_name: str) -> BindingKind | None:
    inferred_kind = command_name.rsplit(' ', maxsplit=1)[-1].rsplit('::', maxsplit=1)[-1]
    if inferred_kind not in BINDING_KINDS:
        return None
    return inferred_kind


def _parse_procedure_value(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
    role: str,
    allow_literal: bool,
    allow_none: bool,
) -> tuple[MetadataSelector | None, str | None]:
    if len(words) == 1 and words[0] == '-':
        if not allow_none:
            raise RuntimeError(
                f'Procedure {role} settings for `{command_name}` do not support `-`.'
            )
        return None, None

    if len(words) >= 2 and words[0] == 'select':
        selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
        if consumed != len(words) - 1:
            raise RuntimeError(
                f'Procedure {role} settings for `{command_name}` must use `{role} select selector`.'
            )
        _validate_procedure_selector(selector, command_name=command_name, role=role)
        return selector, None

    if allow_literal and len(words) == 2 and words[0] == 'literal':
        return None, words[1]

    literal_fragment = '|literal value' if allow_literal else ''
    none_fragment = '|-' if allow_none else ''
    raise RuntimeError(
        f'Procedure {role} settings for `{command_name}` must be '
        f'`{role} select selector{literal_fragment}{none_fragment}`.'
    )


def _validate_procedure_selector(
    selector: MetadataSelector,
    *,
    command_name: str,
    role: str,
) -> None:
    if selector.list_mode or not selector.selects_single_argument:
        raise RuntimeError(
            f'Procedure {role} selectors for `{command_name}` must select exactly one argument.'
        )


def _parse_metadata_form_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    name_span: Span,
    documentation: str | None,
) -> tuple[MetadataCommand, ...]:
    if len(command.words) not in {2, 3}:
        raise RuntimeError(
            f'Form entries for `{command_name}` must be `form {{shape}}` optionally '
            'followed by a clause body.'
        )

    signature = word_static_text(command.words[1])
    if signature is None:
        raise RuntimeError(f'Form entries for `{command_name}` must be fully static.')

    annotation_word = command.words[2] if len(command.words) == 3 else None
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=command_name,
            context_name=context_name,
            context_extends=context_extends,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=command_name,
            context_name=context_name,
            context_extends=context_extends,
            signature=signature,
            documentation=_command_documentation(command.leading_comments) or documentation,
            name_span=name_span,
            options=options,
            subcommands=(),
            annotations=annotations,
        ),
        *nested_commands,
    )


def _parse_metadata_variant_body(
    word: Word,
    *,
    metadata_uri: str,
    command_name: str,
) -> tuple[Command, ...]:
    body_text = _metadata_body_text(word)
    parse_result = Parser().parse_document(
        path=f'{metadata_uri}#{command_name}:variants', text=body_text
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata variants for `{command_name}`: {message}')
    if not parse_result.script.commands:
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies must contain '
            '`form` or `command` entries.'
        )
    return parse_result.script.commands


def _load_metadata_variant_commands(
    commands: tuple[Command, ...],
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    name_span: Span,
    documentation: str | None,
) -> tuple[MetadataCommand, ...]:
    loaded_commands: list[MetadataCommand] = []
    saw_form = False
    for nested_command in commands:
        nested_name = word_static_text(nested_command.words[0])
        if nested_name == 'form':
            saw_form = True
            loaded_commands.extend(
                _parse_metadata_form_entry(
                    nested_command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    command_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                    name_span=name_span,
                    documentation=documentation,
                )
            )
            continue
        if nested_name == 'command':
            loaded_commands.extend(
                _parse_nested_command_entry(
                    nested_command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    parent_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                )
            )
            continue
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies may only contain '
            '`form` and `command` entries.'
        )
    if not saw_form:
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies must declare '
            'at least one `form` entry.'
        )
    return tuple(loaded_commands)


def _annotation_words(command: Command, command_name: str) -> list[str]:
    words: list[str] = []
    for word in command.words:
        static_text = word_static_text(word)
        if static_text is None:
            raise RuntimeError(
                f'Metadata command annotations for `{command_name}` must be fully static.'
            )
        words.append(static_text)
    return words


def _commands_with_derived_subcommands(
    commands: tuple[MetadataCommand, ...],
) -> tuple[MetadataCommand, ...]:
    child_values_by_key: dict[tuple[str | None, str], tuple[str, ...]] = {}
    for context_name in {command.context_name for command in commands}:
        command_names = tuple(
            command.name for command in commands if command.context_name == context_name
        )
        for command_name in command_names:
            prefix = command_name + ' '
            values: dict[str, None] = {}
            for candidate_name in command_names:
                if not candidate_name.startswith(prefix):
                    continue
                remainder = candidate_name[len(prefix) :]
                if not remainder:
                    continue
                values.setdefault(remainder.split(' ', maxsplit=1)[0], None)
            if values:
                child_values_by_key[(context_name, command_name)] = tuple(values)

    if not child_values_by_key:
        return commands

    derived_commands: list[MetadataCommand] = []
    for command in commands:
        derived_values = child_values_by_key.get((command.context_name, command.name))
        if derived_values is None:
            derived_commands.append(command)
            continue

        subcommands = _merge_subcommands(command.subcommands, derived_values)

        derived_commands.append(
            MetadataCommand(
                metadata_path=command.metadata_path,
                uri=command.uri,
                name=command.name,
                context_name=command.context_name,
                context_extends=command.context_extends,
                signature=command.signature,
                documentation=command.documentation,
                name_span=command.name_span,
                options=command.options,
                subcommands=subcommands,
                annotations=command.annotations,
            )
        )

    return tuple(derived_commands)


def _merge_subcommands(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: dict[str, None] = {}
    for group in groups:
        for value in group:
            merged.setdefault(value, None)
    return tuple(merged)


def _metadata_body_text(word: Word) -> str:
    if isinstance(word, BracedWord) and not word.expanded:
        raw_text = word.raw_text
        if raw_text.startswith('{'):
            raw_text = raw_text[1:]
        if raw_text.endswith('}'):
            raw_text = raw_text[:-1]
        return raw_text

    text = word_static_text(word)
    if text is None:
        raise RuntimeError('Metadata command annotation bodies must be static words.')
    return text


def _is_bare_keyword(word: Word, keyword: str) -> bool:
    return isinstance(word, BareWord) and word_static_text(word) == keyword


def _command_documentation(comments: tuple[Token, ...]) -> str | None:
    if not comments:
        return None

    lines = [_comment_text(comment.text) for comment in comments]
    documentation = '\n'.join(lines).strip()
    return documentation or None


def _comment_text(text: str) -> str:
    if not text.startswith('#'):
        return text
    text = text[1:]
    return text[1:] if text.startswith(' ') else text
