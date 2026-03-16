from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from tcl_lsp.analysis.model import BINDING_KINDS, BindingKind
from tcl_lsp.common import Span
from tcl_lsp.metadata_paths import metadata_dir
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import BracedWord, Command, Token, Word

_META_DIR = metadata_dir()

type SourceBase = Literal['call-source-directory', 'proc-source-parent']
type MetadataOptionKind = Literal['flag', 'value', 'stop']
type OptionScanState = Literal['ok', 'dynamic', 'unknown-option', 'missing-option-value']
type MetadataValueSetKind = Literal['keyword', 'subcommand']


@dataclass(frozen=True, slots=True)
class MetadataSelector:
    start_index: int
    all_remaining: bool
    list_mode: bool
    after_options: bool


@dataclass(frozen=True, slots=True)
class MetadataOption:
    name: str
    kind: MetadataOptionKind


@dataclass(frozen=True, slots=True)
class MetadataValueSet:
    selector: MetadataSelector
    kind: MetadataValueSetKind
    values: tuple[str, ...]


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


type MetadataAnnotation = (
    MetadataBind | MetadataRef | MetadataScriptBody | MetadataSource | MetadataPackage
)


@dataclass(frozen=True, slots=True)
class MetadataCommand:
    metadata_path: Path
    uri: str
    name: str
    signature: str
    documentation: str | None
    name_span: Span
    options: tuple[MetadataOption, ...]
    value_sets: tuple[MetadataValueSet, ...]
    annotations: tuple[MetadataAnnotation, ...]


@lru_cache(maxsize=None)
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
        if word_static_text(command.words[1]) != 'command':
            continue

        if len(command.words) not in {4, 5}:
            raise RuntimeError(
                'Metadata command entries must be `meta command name {args}` '
                'optionally followed by an annotation body.'
            )

        command_name = word_static_text(command.words[2])
        signature = word_static_text(command.words[3])
        if command_name is None or signature is None:
            raise RuntimeError(
                'Metadata command entries must be fully static '
                '`meta command name {args}` declarations.'
            )

        options: tuple[MetadataOption, ...] = ()
        value_sets: tuple[MetadataValueSet, ...] = ()
        annotations: tuple[MetadataAnnotation, ...] = ()
        if len(command.words) == 5:
            options, value_sets, annotations = _parse_annotation_body(
                metadata_uri=metadata_uri,
                command_name=command_name,
                body_text=_metadata_body_text(command.words[4]),
            )

        commands.append(
            MetadataCommand(
                metadata_path=metadata_path,
                uri=metadata_uri,
                name=command_name,
                signature=signature,
                documentation=_command_documentation(command.leading_comments),
                name_span=command.words[2].content_span,
                options=options,
                value_sets=value_sets,
                annotations=annotations,
            )
        )

    if not commands:
        return ()
    return _commands_with_derived_subcommands(tuple(commands))


@lru_cache(maxsize=1)
def all_metadata_commands() -> tuple[MetadataCommand, ...]:
    commands: list[MetadataCommand] = []
    for metadata_path in sorted(_META_DIR.rglob('*.tcl')):
        commands.extend(load_metadata_commands(metadata_path))
    return tuple(commands)


def select_argument_indices(
    selector: MetadataSelector,
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
) -> tuple[int, ...] | None:
    if selector.after_options:
        scan_result = scan_command_options(arg_texts, options)
        if scan_result.state not in {'ok', 'dynamic'}:
            return None
        positional_indices = scan_result.positional_indices
        if selector.start_index >= len(positional_indices):
            return ()
        if selector.all_remaining:
            return positional_indices[selector.start_index :]
        return positional_indices[selector.start_index : selector.start_index + 1]

    if selector.start_index >= len(arg_texts):
        return ()
    if selector.all_remaining:
        return tuple(range(selector.start_index, len(arg_texts)))
    return (selector.start_index,)


def scan_command_options(
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
) -> OptionScanResult:
    if not options:
        return OptionScanResult(
            state='ok',
            positional_indices=tuple(range(len(arg_texts))),
        )

    option_specs = {option.name: option for option in options}
    positional_indices: list[int] = []
    index = 0
    while index < len(arg_texts):
        arg_text = arg_texts[index]
        if arg_text is None:
            positional_indices.extend(range(index, len(arg_texts)))
            return OptionScanResult(
                state='dynamic',
                positional_indices=tuple(positional_indices),
            )

        option = option_specs.get(arg_text)
        if option is None:
            if arg_text.startswith('-') and arg_text != '-':
                return OptionScanResult(
                    state='unknown-option',
                    positional_indices=tuple(positional_indices),
                    option_index=index,
                    option_name=arg_text,
                )
            positional_indices.extend(range(index, len(arg_texts)))
            return OptionScanResult(
                state='ok',
                positional_indices=tuple(positional_indices),
            )

        if option.kind == 'flag':
            index += 1
            continue
        if option.kind == 'value':
            if index + 1 >= len(arg_texts):
                return OptionScanResult(
                    state='missing-option-value',
                    positional_indices=tuple(positional_indices),
                    option_index=index,
                    option_name=arg_text,
                )
            index += 2
            continue
        positional_indices.extend(range(index + 1, len(arg_texts)))
        return OptionScanResult(
            state='ok',
            positional_indices=tuple(positional_indices),
        )

    return OptionScanResult(
        state='ok',
        positional_indices=tuple(positional_indices),
    )


def _parse_annotation_body(
    *,
    metadata_uri: str,
    command_name: str,
    body_text: str,
) -> tuple[tuple[MetadataOption, ...], tuple[MetadataValueSet, ...], tuple[MetadataAnnotation, ...]]:
    annotation_uri = f'{metadata_uri}#{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=body_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata command annotations for `{command_name}`: {message}')

    options: list[MetadataOption] = []
    value_sets: list[MetadataValueSet] = []
    annotations: list[MetadataAnnotation] = []
    for command in parse_result.script.commands:
        annotation_name = word_static_text(command.words[0])
        if annotation_name is None:
            raise RuntimeError(
                f'Metadata command annotations for `{command_name}` must be static commands.'
            )

        if annotation_name == 'option':
            options.append(_parse_option_annotation(command, command_name))
            continue
        if annotation_name == 'keyword':
            value_sets.append(_parse_value_set_annotation(command, command_name, kind='keyword'))
            continue
        if annotation_name == 'subcommand':
            value_sets.append(_parse_value_set_annotation(command, command_name, kind='subcommand'))
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
        raise RuntimeError(
            f'Unknown metadata command annotation `{annotation_name}` for `{command_name}`.'
        )

    return tuple(options), tuple(value_sets), tuple(annotations)


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


def _parse_value_set_annotation(
    command: Command,
    command_name: str,
    *,
    kind: MetadataValueSetKind,
) -> MetadataValueSet:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    values = tuple(words[consumed + 1 :])
    if consumed >= len(words) - 1 or not values:
        raise RuntimeError(
            f'{kind.title()} annotations for `{command_name}` must be '
            f'`{kind} selector value ...`.'
        )
    _validate_single_argument_selector(selector, command_name, kind=kind)
    return MetadataValueSet(
        selector=selector,
        kind=kind,
        values=values,
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


def _validate_package_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or selector.all_remaining:
        raise RuntimeError(
            f'Package annotations for `{command_name}` must select a single argument.'
        )


def _validate_single_argument_selector(
    selector: MetadataSelector,
    command_name: str,
    *,
    kind: MetadataValueSetKind,
) -> None:
    if selector.list_mode or selector.all_remaining:
        raise RuntimeError(
            f'{kind.title()} annotations for `{command_name}` must select a single argument.'
        )


def _parse_selector_tokens(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
) -> tuple[MetadataSelector, int]:
    index = 0
    after_options = False
    list_mode = False

    if index < len(words) and words[index] == 'after-options':
        after_options = True
        index += 1
    if index < len(words) and words[index] == 'list':
        list_mode = True
        index += 1
    if index >= len(words):
        raise RuntimeError(f'Metadata selector for `{command_name}` is missing an index.')

    token = words[index]
    all_remaining = token.endswith('..')
    number_text = token[:-2] if all_remaining else token
    if not number_text.isdigit() or number_text == '0':
        raise RuntimeError(
            f'Metadata selector for `{command_name}` must use a positive 1-based index.'
        )

    return (
        MetadataSelector(
            start_index=int(number_text) - 1,
            all_remaining=all_remaining,
            list_mode=list_mode,
            after_options=after_options,
        ),
        index + 1,
    )


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
    child_values_by_name: dict[str, tuple[str, ...]] = {}
    command_names = tuple(command.name for command in commands)

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
            child_values_by_name[command_name] = tuple(values)

    if not child_values_by_name:
        return commands

    derived_selector = MetadataSelector(
        start_index=0,
        all_remaining=False,
        list_mode=False,
        after_options=False,
    )
    derived_commands: list[MetadataCommand] = []
    for command in commands:
        derived_values = child_values_by_name.get(command.name)
        if derived_values is None:
            derived_commands.append(command)
            continue

        existing = next(
            (
                value_set
                for value_set in command.value_sets
                if value_set.kind == 'subcommand' and value_set.selector == derived_selector
            ),
            None,
        )
        if existing is None:
            value_sets = command.value_sets + (
                MetadataValueSet(
                    selector=derived_selector,
                    kind='subcommand',
                    values=derived_values,
                ),
            )
        else:
            merged_values = tuple(dict.fromkeys(existing.values + derived_values))
            value_sets = tuple(
                MetadataValueSet(
                    selector=value_set.selector,
                    kind=value_set.kind,
                    values=merged_values,
                )
                if value_set is existing
                else value_set
                for value_set in command.value_sets
            )

        derived_commands.append(
            MetadataCommand(
                metadata_path=command.metadata_path,
                uri=command.uri,
                name=command.name,
                signature=command.signature,
                documentation=command.documentation,
                name_span=command.name_span,
                options=command.options,
                value_sets=value_sets,
                annotations=command.annotations,
            )
        )

    return tuple(derived_commands)


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
