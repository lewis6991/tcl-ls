from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from tcl_lsp.analysis.model import BINDING_KINDS, BindingKind
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Span
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY, MetadataRegistry
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import BracedWord, Command, Token, Word

_MISSING = object()

type SourceBase = Literal['call-source-directory', 'proc-source-parent']
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
class MetadataScriptBody:
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
    owner_selector: MetadataSelector


@dataclass(frozen=True, slots=True)
class MetadataProcedure:
    member_name_index: int | None
    parameter_index: int | None
    body_index: int
    body_context: str | None


@dataclass(frozen=True, slots=True)
class MetadataPlugin:
    script_path: Path
    proc_name: str


type MetadataAnnotation = (
    MetadataBind
    | MetadataRef
    | MetadataScriptBody
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
    signature: str
    documentation: str | None
    name_span: Span
    options: tuple[MetadataOption, ...]
    subcommands: tuple[str, ...]
    annotations: tuple[MetadataAnnotation, ...]


@metadata_lru_cache(maxsize=None)
def load_metadata_commands(metadata_path: Path) -> tuple[MetadataCommand, ...]:
    metadata_uri = metadata_path.as_uri()
    text = metadata_path.read_text(encoding='utf-8')
    parse_result = Parser().parse_document(path=metadata_uri, text=text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata file `{metadata_path.name}`: {message}')

    commands: list[MetadataCommand] = []
    for command in parse_result.script.commands:
        if word_static_text(command.words[0]) != 'meta':
            continue
        entry_kind = word_static_text(command.words[1])
        if entry_kind == 'command':
            commands.extend(
                _parse_metadata_command_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                )
            )
            continue
        if entry_kind == 'context':
            commands.extend(
                _parse_metadata_context_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                )
            )

    if not commands:
        return ()
    return _commands_with_derived_subcommands(tuple(commands))


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


def _parse_metadata_command_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    context_name: str | None = None,
    parent_name: str | None = None,
) -> tuple[MetadataCommand, ...]:
    if context_name is None:
        if len(command.words) not in {4, 5}:
            raise RuntimeError(
                'Metadata command entries must be `meta command name {args}` '
                'optionally followed by an annotation body.'
            )
        command_name = word_static_text(command.words[2])
        signature = word_static_text(command.words[3])
        name_word = command.words[2]
        annotation_word = command.words[4] if len(command.words) == 5 else None
    else:
        if len(command.words) not in {3, 4}:
            raise RuntimeError(
                'Metadata context command entries must be '
                '`command name {args}` optionally followed by an annotation body.'
            )
        command_name = word_static_text(command.words[1])
        signature = word_static_text(command.words[2])
        name_word = command.words[1]
        annotation_word = command.words[3] if len(command.words) == 4 else None

    if command_name is None or signature is None:
        raise RuntimeError('Metadata command entries must be fully static declarations.')
    if ' ' in command_name:
        raise RuntimeError(
            'Metadata command entries must use single command names. '
            'Use nested `subcommand name {signature}` declarations for subcommands.'
        )

    full_name = command_name if parent_name is None else f'{parent_name} {command_name}'
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=full_name,
            context_name=context_name,
            signature=signature,
            documentation=_command_documentation(command.leading_comments),
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
) -> tuple[MetadataCommand, ...]:
    if len(command.words) != 4:
        raise RuntimeError('Metadata context entries must be `meta context name { ... }`.')

    context_name = word_static_text(command.words[2])
    if context_name is None:
        raise RuntimeError('Metadata context entries must have a static context name.')

    body_text = _metadata_body_text(command.words[3])
    parse_result = Parser().parse_document(
        path=f'{metadata_uri}#context:{context_name}', text=body_text
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(
            f'Invalid metadata context `{context_name}` in `{metadata_path.name}`: {message}'
        )

    commands: list[MetadataCommand] = []
    for nested_command in parse_result.script.commands:
        if word_static_text(nested_command.words[0]) != 'command':
            raise RuntimeError(
                f'Metadata context `{context_name}` entries must use `command name {{args}}`.'
            )
        commands.extend(
            _parse_metadata_command_entry(
                nested_command,
                metadata_path=metadata_path,
                metadata_uri=metadata_uri,
                context_name=context_name,
            )
        )

    return tuple(commands)


def select_argument_indices(
    selector: MetadataSelector,
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...] | None = None,
) -> tuple[int, ...] | None:
    expanded_flags = _normalized_argument_expansion_flags(arg_texts, arg_expanded)
    if selector.after_options:
        scan_result = scan_command_options(arg_texts, options, expanded_flags)
        if scan_result.state not in {'ok', 'dynamic', 'unstable'}:
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
        if annotation_name == 'subcommand':
            nested_commands.extend(
                _parse_metadata_subcommand_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    parent_name=command_name,
                    context_name=context_name,
                )
            )
            continue
        if annotation_name == 'bind':
            annotations.append(_parse_bind_annotation(command, command_name))
            continue
        if annotation_name == 'ref':
            annotations.append(_parse_ref_annotation(command, command_name))
            continue
        if annotation_name == 'script-body':
            annotations.append(_parse_script_body_annotation(command, command_name))
            continue
        if annotation_name == 'source':
            annotations.append(_parse_source_annotation(command, command_name))
            continue
        if annotation_name == 'package':
            annotations.append(_parse_package_annotation(command, command_name))
            continue
        if annotation_name == 'context':
            annotations.append(_parse_context_annotation(command, command_name))
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


def _parse_metadata_subcommand_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    parent_name: str,
    context_name: str | None,
) -> tuple[MetadataCommand, ...]:
    if len(command.words) not in {3, 4}:
        raise RuntimeError(
            f'Subcommand annotations for `{parent_name}` must be '
            '`subcommand name {signature}` optionally followed by an annotation body.'
        )

    subcommand_name = word_static_text(command.words[1])
    signature = word_static_text(command.words[2])
    if subcommand_name is None or signature is None:
        raise RuntimeError(
            f'Subcommand annotations for `{parent_name}` must be fully static declarations.'
        )
    if ' ' in subcommand_name:
        raise RuntimeError(
            f'Subcommand annotations for `{parent_name}` must use single subcommand names.'
        )

    annotation_word = command.words[3] if len(command.words) == 4 else None
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    full_name = f'{parent_name} {subcommand_name}'
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=full_name,
            context_name=context_name,
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
                f'Bind annotations for `{command_name}` must be `bind selector ?kind?`.'
            )
        kind = _parse_binding_kind(words[-1], command_name)
    return MetadataBind(selector=selector, kind=kind)


def _parse_ref_annotation(command: Command, command_name: str) -> MetadataRef:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    if consumed != len(words) - 1:
        raise RuntimeError(f'Ref annotations for `{command_name}` must be `ref selector`.')
    return MetadataRef(selector=selector)


def _parse_script_body_annotation(command: Command, command_name: str) -> MetadataScriptBody:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    if consumed != len(words) - 1:
        raise RuntimeError(
            f'Script-body annotations for `{command_name}` must be `script-body selector`.'
        )
    return MetadataScriptBody(selector=selector)


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
    if len(words) != 2:
        selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
        if consumed != len(words) - 1:
            raise RuntimeError(
                f'Package annotations for `{command_name}` must be `package name` '
                'or `package selector`.'
            )
        _validate_package_selector(selector, command_name)
        return MetadataPackage(selector=selector, literal_package=None)

    try:
        selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    except RuntimeError:
        selector = None
        consumed = 0
    if selector is not None and consumed == 1:
        _validate_package_selector(selector, command_name)
        return MetadataPackage(selector=selector, literal_package=None)
    return MetadataPackage(selector=None, literal_package=words[1])


def _parse_context_annotation(command: Command, command_name: str) -> MetadataContext:
    if len(command.words) != 3:
        raise RuntimeError(
            f'Context annotations for `{command_name}` must be '
            '`context context-name { body selector; owner selector }`.'
        )

    context_name = word_static_text(command.words[1])
    if context_name is None:
        raise RuntimeError(
            f'Context annotations for `{command_name}` must use a static context name.'
        )

    config_text = _metadata_body_text(command.words[2])
    annotation_uri = f'context:{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=config_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid context annotation for `{command_name}`: {message}')

    body_selector: MetadataSelector | None = None
    owner_selector: MetadataSelector | None = None
    for nested_command in parse_result.script.commands:
        nested_words = _annotation_words(nested_command, command_name)
        nested_name = nested_words[0]
        if nested_name == 'body':
            if body_selector is not None:
                raise RuntimeError(
                    f'Context annotations for `{command_name}` may only declare one `body`.'
                )
            selector, consumed = _parse_selector_tokens(
                nested_words[1:],
                command_name=command_name,
            )
            if consumed != len(nested_words) - 1:
                raise RuntimeError(
                    f'Context body selectors for `{command_name}` must be `body selector`.'
                )
            _validate_context_body_selector(selector, command_name)
            body_selector = selector
            continue
        if nested_name == 'owner':
            if owner_selector is not None:
                raise RuntimeError(
                    f'Context annotations for `{command_name}` may only declare one `owner`.'
                )
            selector, consumed = _parse_selector_tokens(
                nested_words[1:],
                command_name=command_name,
            )
            if consumed != len(nested_words) - 1:
                raise RuntimeError(
                    f'Context owner selectors for `{command_name}` must be `owner selector`.'
                )
            _validate_context_owner_selector(selector, command_name)
            owner_selector = selector
            continue
        raise RuntimeError(f'Unknown context setting `{nested_name}` for `{command_name}`.')

    if body_selector is None or owner_selector is None:
        raise RuntimeError(
            f'Context annotations for `{command_name}` must declare both `body` and `owner`.'
        )

    return MetadataContext(
        body_selector=body_selector,
        context_name=context_name,
        owner_selector=owner_selector,
    )


def _parse_procedure_annotation(command: Command, command_name: str) -> MetadataProcedure:
    if len(command.words) != 2:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must be '
            '`procedure { name index|-; params index|-; body index; '
            '? context body-context ? }`.'
        )

    config_text = _metadata_body_text(command.words[1])
    annotation_uri = f'procedure:{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=config_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid procedure annotation for `{command_name}`: {message}')

    member_name_index: int | None | object = _MISSING
    parameter_index: int | None | object = _MISSING
    body_index: int | object = _MISSING
    body_context: str | None = None

    for nested_command in parse_result.script.commands:
        nested_words = _annotation_words(nested_command, command_name)
        nested_name = nested_words[0]
        if nested_name == 'name':
            if member_name_index is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `name`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure name selectors for `{command_name}` must be `name index|-`.'
                )
            member_name_index = _parse_optional_procedure_index(
                nested_words[1],
                command_name=command_name,
                role='member name',
            )
            continue
        if nested_name == 'params':
            if parameter_index is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `params`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure parameter selectors for `{command_name}` must be `params index|-`.'
                )
            parameter_index = _parse_optional_procedure_index(
                nested_words[1],
                command_name=command_name,
                role='parameter',
            )
            continue
        if nested_name == 'body':
            if body_index is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `body`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure body selectors for `{command_name}` must be `body index`.'
                )
            body_index = _parse_required_procedure_index(
                nested_words[1],
                command_name=command_name,
                role='body',
            )
            continue
        if nested_name == 'context':
            if body_context is not None:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `context`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure body contexts for `{command_name}` must be `context name`.'
                )
            body_context = nested_words[1]
            continue
        raise RuntimeError(f'Unknown procedure setting `{nested_name}` for `{command_name}`.')

    if member_name_index is _MISSING or parameter_index is _MISSING or body_index is _MISSING:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must declare `name`, `params`, and `body`.'
        )

    return MetadataProcedure(
        member_name_index=cast(int | None, member_name_index),
        parameter_index=cast(int | None, parameter_index),
        body_index=cast(int, body_index),
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
    if selector.list_mode or selector.after_options:
        raise RuntimeError(
            f'Context annotations for `{command_name}` must use direct positional selectors.'
        )


def _validate_context_owner_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or selector.after_options or not selector.selects_single_argument:
        raise RuntimeError(
            f'Context annotations for `{command_name}` must select exactly one owner argument.'
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
    if text == 'call-source-directory':
        return 'call-source-directory'
    if text == 'proc-source-parent':
        return 'proc-source-parent'
    raise RuntimeError(f'Unknown metadata source base `{text}`.')


def _parse_binding_kind(text: str, command_name: str) -> BindingKind:
    if text not in BINDING_KINDS:
        raise RuntimeError(f'Unknown metadata binding kind `{text}` for `{command_name}`.')
    return text


def _parse_optional_procedure_index(
    text: str,
    *,
    command_name: str,
    role: str,
) -> int | None:
    if text == '-':
        return None
    return _parse_required_procedure_index(text, command_name=command_name, role=role)


def _parse_required_procedure_index(
    text: str,
    *,
    command_name: str,
    role: str,
) -> int:
    if not text.isdigit() or text == '0':
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must use a positive '
            f'1-based {role} index or `-`.'
        )
    return int(text) - 1


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
