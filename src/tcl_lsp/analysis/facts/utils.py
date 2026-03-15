from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlparse

from tcl_lsp.common import Position, Span
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    LiteralText,
    VariableSubstitution,
    Word,
)


def extract_static_script(word: Word) -> tuple[str, Position] | None:
    text = word_static_text(word)
    if text is None:
        return None
    return text, _body_start(word)


def command_documentation(command: Command) -> str | None:
    if not command.leading_comments:
        return None

    lines = [_comment_text(comment.text) for comment in command.leading_comments]
    documentation = '\n'.join(lines).strip()
    return documentation or None


def _comment_text(text: str) -> str:
    if not text.startswith('#'):
        return text
    text = text[1:]
    return text[1:] if text.startswith(' ') else text


def _body_start(word: Word) -> Position:
    return word.content_span.start


def body_span(word: Word) -> Span:
    return word.content_span


def qualify_name(name: str, current_namespace: str) -> str:
    if name.startswith('::'):
        return _normalize_qualified_name(name)
    if current_namespace == '::':
        return f'::{name}'
    return f'{current_namespace}::{name}'


def qualify_namespace(name: str, current_namespace: str) -> str:
    if name == '::':
        return '::'
    return qualify_name(name, current_namespace)


def normalize_command_name(name: str) -> str:
    return name[2:] if name.startswith('::') else name


def _normalize_qualified_name(name: str) -> str:
    segments = [segment for segment in name.split('::') if segment]
    if not segments:
        return '::'
    return '::' + '::'.join(segments)


def namespace_for_name(qualified_name: str) -> str:
    segments = [segment for segment in qualified_name.split('::') if segment]
    if len(segments) <= 1:
        return '::'
    return '::' + '::'.join(segments[:-1])


def name_tail(qualified_name: str) -> str:
    segments = [segment for segment in qualified_name.split('::') if segment]
    if not segments:
        return qualified_name
    return segments[-1]


def namespace_scope_id(namespace: str) -> str:
    return f'namespace::{namespace}'


def proc_symbol_id(uri: str, qualified_name: str, offset: int) -> str:
    return f'proc::{uri}::{qualified_name}::{offset}'


def variable_symbol_id(uri: str, scope_id: str, name: str) -> str:
    return f'var::{uri}::{scope_id}::{name}'


def extract_ifneeded_source_uri(word: Word, source_id: str) -> str | None:
    package_script = _single_nested_command(word)
    if package_script is None or len(package_script.words) != 3:
        return None

    if word_static_text(package_script.words[0]) != 'list':
        return None
    if word_static_text(package_script.words[1]) != 'source':
        return None

    file_join_command = _single_nested_command(package_script.words[2])
    if file_join_command is None or len(file_join_command.words) < 4:
        return None

    if word_static_text(file_join_command.words[0]) != 'file':
        return None
    if word_static_text(file_join_command.words[1]) != 'join':
        return None
    if not _is_dir_variable(file_join_command.words[2]):
        return None

    relative_parts: list[str] = []
    for path_word in file_join_command.words[3:]:
        part = word_static_text(path_word)
        if part is None:
            return None
        relative_parts.append(part)

    source_path = _source_id_to_path(source_id)
    if source_path is None:
        return None

    resolved_path = source_path.parent.joinpath(*relative_parts)
    return _path_to_source_id(resolved_path, source_id)


def extract_static_source_uri(
    command: Command,
    source_id: str,
    *,
    variables: Mapping[str, str] | None = None,
) -> str | None:
    if len(command.words) < 2:
        return None

    source_word = command.words[1]
    if word_static_text(source_word) == '-encoding':
        if len(command.words) < 4:
            return None
        source_word = command.words[3]
    elif len(command.words) != 2:
        return None

    path_text = extract_static_text(source_word, source_id=source_id, variables=variables)
    if path_text is None:
        return None

    source_path = Path(path_text).expanduser()
    if not source_path.is_absolute():
        return None
    return _path_to_source_id(source_path, source_id)


def extract_static_text(
    word: Word,
    *,
    source_id: str,
    variables: Mapping[str, str] | None = None,
) -> str | None:
    if isinstance(word, BracedWord):
        return word.text

    resolved_parts: list[str] = []
    variable_values = {} if variables is None else dict(variables)
    for part in word.parts:
        if isinstance(part, LiteralText):
            resolved_parts.append(part.text)
            continue
        if isinstance(part, VariableSubstitution):
            value = variable_values.get(part.name)
            if value is None:
                return None
            resolved_parts.append(value)
            continue
        value = _evaluate_static_command_substitution(
            part,
            source_id=source_id,
            variables=variable_values,
        )
        if value is None:
            return None
        resolved_parts.append(value)
    return ''.join(resolved_parts)


def _single_nested_command(word: Word) -> Command | None:
    if isinstance(word, BracedWord):
        return None
    if len(word.parts) != 1:
        return None
    part = word.parts[0]
    if not isinstance(part, CommandSubstitution):
        return None
    if len(part.script.commands) != 1:
        return None
    return part.script.commands[0]


def _is_dir_variable(word: Word) -> bool:
    if isinstance(word, BracedWord):
        return False
    if len(word.parts) != 1:
        return False
    part = word.parts[0]
    return isinstance(part, VariableSubstitution) and part.name == 'dir'


def _evaluate_static_command_substitution(
    substitution: CommandSubstitution,
    *,
    source_id: str,
    variables: Mapping[str, str],
) -> str | None:
    if len(substitution.script.commands) != 1:
        return None
    return _evaluate_static_command(
        substitution.script.commands[0],
        source_id=source_id,
        variables=variables,
    )


def _evaluate_static_command(
    command: Command,
    *,
    source_id: str,
    variables: Mapping[str, str],
) -> str | None:
    if not command.words:
        return None

    command_name = word_static_text(command.words[0])
    if command_name == 'pwd' and len(command.words) == 1:
        return str(Path.cwd())

    if (
        command_name == 'info'
        and len(command.words) == 2
        and word_static_text(command.words[1]) == 'script'
    ):
        source_path = _source_id_to_path(source_id)
        if source_path is None:
            return None
        return str(source_path)

    if command_name != 'file' or len(command.words) < 2:
        return None

    subcommand = word_static_text(command.words[1])
    if subcommand == 'join' and len(command.words) >= 3:
        result_path: Path | None = None
        for path_word in command.words[2:]:
            path_text = extract_static_text(path_word, source_id=source_id, variables=variables)
            if path_text is None:
                return None
            if result_path is None:
                result_path = Path(path_text)
            else:
                result_path = result_path / Path(path_text)
        if result_path is None:
            return ''
        return str(result_path)

    if subcommand == 'dirname' and len(command.words) == 3:
        path_text = extract_static_text(command.words[2], source_id=source_id, variables=variables)
        if path_text is None:
            return None
        return str(Path(path_text).parent)

    if subcommand == 'normalize' and len(command.words) == 3:
        path_text = extract_static_text(command.words[2], source_id=source_id, variables=variables)
        if path_text is None:
            return None
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path.resolve(strict=False))

    return None


def _source_id_to_path(source_id: str) -> Path | None:
    parsed = urlparse(source_id)
    if parsed.scheme == 'file':
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_id)


def _path_to_source_id(path: Path, source_id: str) -> str:
    parsed = urlparse(source_id)
    if parsed.scheme == 'file':
        return path.resolve(strict=False).as_uri()
    return str(path)
