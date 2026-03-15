from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tcl_lsp.analysis.model import DefinitionTarget
from tcl_lsp.common import Location
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import Token

_METADATA_PATH = Path(__file__).resolve().parents[1] / 'data' / 'tcl_builtin_commands.tcl'
_METADATA_URI = _METADATA_PATH.as_uri()


@dataclass(frozen=True, slots=True)
class BuiltinOverload:
    symbol_id: str
    signature: str
    documentation: str
    location: Location


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    name: str
    overloads: tuple[BuiltinOverload, ...]


@lru_cache(maxsize=1)
def builtin_commands() -> dict[str, BuiltinCommand]:
    text = _METADATA_PATH.read_text(encoding='utf-8')
    parse_result = Parser().parse_document(path=_METADATA_URI, text=text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid builtin command metadata: {message}')

    commands: dict[str, list[BuiltinOverload]] = {}
    for command in parse_result.script.commands:
        command_name = word_static_text(command.words[0])
        if command_name != 'meta':
            continue

        if len(command.words) != 4:
            raise RuntimeError(
                'Builtin command metadata entries must be `meta command name {args}`.'
            )

        metadata_kind = word_static_text(command.words[1])
        builtin_name = word_static_text(command.words[2])
        parameter_list = word_static_text(command.words[3])
        if metadata_kind != 'command' or builtin_name is None or parameter_list is None:
            raise RuntimeError(
                'Builtin command metadata entries must be fully static `meta command name {args}`.'
            )

        documentation = _command_documentation(command.leading_comments)
        if not documentation:
            raise RuntimeError(f'Builtin command `{builtin_name}` is missing documentation.')

        commands.setdefault(builtin_name, []).append(
            BuiltinOverload(
                symbol_id=_builtin_symbol_id(builtin_name, command.words[2].span.start.offset),
                signature=_signature(builtin_name, parameter_list),
                documentation=documentation,
                location=Location(uri=_METADATA_URI, span=command.words[2].span),
            )
        )

    if not commands:
        raise RuntimeError('No builtin command metadata entries were loaded.')

    return {
        name: BuiltinCommand(name=name, overloads=tuple(overloads))
        for name, overloads in commands.items()
    }


def builtin_command(name: str) -> BuiltinCommand | None:
    return builtin_commands().get(name)


@lru_cache(maxsize=1)
def builtin_definition_targets() -> tuple[DefinitionTarget, ...]:
    definitions: list[DefinitionTarget] = []
    for builtin in builtin_commands().values():
        for overload in builtin.overloads:
            definitions.append(
                DefinitionTarget(
                    symbol_id=overload.symbol_id,
                    name=builtin.name,
                    kind='function',
                    location=overload.location,
                    detail=overload.signature,
                )
            )
    return tuple(definitions)


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


def _signature(name: str, parameter_list: str) -> str:
    return f'{name} {{{parameter_list}}}'


def _builtin_symbol_id(name: str, offset: int) -> str:
    return f'builtin::{name}::{offset}'
