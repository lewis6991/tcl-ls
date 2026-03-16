from __future__ import annotations

from collections.abc import Iterator

from tcl_lsp.parser.model import (
    BracedWord,
    CommandSubstitution,
    LiteralText,
    Script,
    VariableSubstitution,
    Word,
    WordPart,
)

_BARE_VARIABLE_SEGMENT_CHARS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
)


def iter_word_parts(word: Word) -> Iterator[WordPart]:
    if isinstance(word, BracedWord):
        return
    yield from word.parts


def word_static_text(word: Word) -> str | None:
    if word.expanded:
        return None
    if isinstance(word, BracedWord):
        return word.text

    if len(word.parts) == 1:
        part = word.parts[0]
        if isinstance(part, LiteralText):
            return part.text
        return None

    parts: list[str] = []
    for part in word.parts:
        if isinstance(part, LiteralText):
            parts.append(part.text)
            continue
        return None
    return ''.join(parts)


def collect_variable_substitutions(word: Word) -> tuple[VariableSubstitution, ...]:
    if isinstance(word, BracedWord):
        return ()

    if len(word.parts) == 1:
        part = word.parts[0]
        if isinstance(part, VariableSubstitution):
            return (part,)
        if isinstance(part, LiteralText):
            return ()

    substitutions: list[VariableSubstitution] = []
    for part in word.parts:
        if isinstance(part, VariableSubstitution):
            substitutions.append(part)
            continue
        if isinstance(part, CommandSubstitution):
            substitutions.extend(_collect_from_script(part.script))
    return tuple(substitutions)


def _collect_from_script(script: Script) -> list[VariableSubstitution]:
    substitutions: list[VariableSubstitution] = []
    for command in script.commands:
        for word in command.words:
            if isinstance(word, BracedWord):
                continue
            for part in word.parts:
                if isinstance(part, VariableSubstitution):
                    substitutions.append(part)
                elif isinstance(part, CommandSubstitution):
                    substitutions.extend(_collect_from_script(part.script))
    return substitutions


def consume_bare_variable_name_end(text: str, start_index: int) -> int:
    index = start_index
    if index >= len(text):
        return start_index

    if text.startswith('::', index):
        index += 2
    elif text[index] in _BARE_VARIABLE_SEGMENT_CHARS:
        index += 1
    else:
        return start_index

    while index < len(text):
        if text[index] in _BARE_VARIABLE_SEGMENT_CHARS:
            index += 1
            continue
        if text.startswith('::', index):
            index += 2
            continue
        break

    return index
