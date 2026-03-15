from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from tcl_lsp.common import Position, Span
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
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
