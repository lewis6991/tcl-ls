from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.common import Position, Span

_SIMPLE_NAME_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:')


@dataclass(frozen=True, slots=True)
class ListItem:
    text: str
    span: Span
    content_start: Position


@dataclass(frozen=True, slots=True)
class ConditionVariableSubstitution:
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class ConditionCommandSubstitution:
    text: str
    span: Span
    content_span: Span


def is_simple_name(name: str) -> bool:
    return bool(name) and all(char in _SIMPLE_NAME_CHARS for char in name)


def scan_static_tcl_substitutions(
    text: str,
    start_position: Position,
) -> list[ConditionVariableSubstitution | ConditionCommandSubstitution]:
    substitutions: list[ConditionVariableSubstitution | ConditionCommandSubstitution] = []
    index = 0
    position = start_position

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            position = position.advance(current_char)
            index += 1
            if index < len(text):
                position = position.advance(text[index])
                index += 1
            continue
        if current_char == '$':
            variable = _consume_static_variable_substitution(text, index, position)
            if variable is not None:
                substitutions.append(variable)
                index += variable.span.end.offset - variable.span.start.offset
                position = variable.span.end
                continue
            position = position.advance(current_char)
            index += 1
            continue
        if current_char == '[':
            command_substitution = _consume_static_command_substitution(text[index:], position)
            if command_substitution is not None:
                substitutions.append(command_substitution)
                consumed = (
                    command_substitution.span.end.offset - command_substitution.span.start.offset
                )
                index += consumed
                position = command_substitution.span.end
                continue
        position = position.advance(current_char)
        index += 1

    return substitutions


def _consume_static_variable_substitution(
    text: str,
    start_index: int,
    start_position: Position,
) -> ConditionVariableSubstitution | None:
    index = start_index + 1
    position = start_position.advance('$')

    if index >= len(text):
        return None

    current_char = text[index]
    if current_char == '{':
        position = position.advance(current_char)
        index += 1
        name_start = index
        while index < len(text) and text[index] not in {'}', '\n'}:
            position = position.advance(text[index])
            index += 1
        if index >= len(text) or text[index] != '}':
            return None
        name = text[name_start:index].strip()
        position = position.advance('}')
        if not name:
            return None
        return ConditionVariableSubstitution(
            name=name,
            span=Span(start=start_position, end=position),
        )

    if current_char not in _SIMPLE_NAME_CHARS:
        return None

    while index < len(text) and text[index] in _SIMPLE_NAME_CHARS:
        position = position.advance(text[index])
        index += 1
    return ConditionVariableSubstitution(
        name=text[start_index + 1 : index],
        span=Span(start=start_position, end=position),
    )


def _consume_static_command_substitution(
    text: str,
    start_position: Position,
) -> ConditionCommandSubstitution | None:
    index = 1
    position = start_position.advance('[')
    content_start = position

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            position = position.advance(current_char)
            index += 1
            if index < len(text):
                position = position.advance(text[index])
                index += 1
            continue
        if current_char == '{':
            _, consumed, position, _ = _consume_braced_item(text[index:], position)
            index += consumed
            continue
        if current_char == '"':
            _, consumed, position, _ = _consume_quoted_item(text[index:], position)
            index += consumed
            continue
        if current_char == '[':
            nested = _consume_static_command_substitution(text[index:], position)
            if nested is None:
                return None
            index += nested.span.end.offset - nested.span.start.offset
            position = nested.span.end
            continue
        if current_char == ']':
            end_position = position.advance(']')
            return ConditionCommandSubstitution(
                text=text[1:index],
                span=Span(start=start_position, end=end_position),
                content_span=Span(start=content_start, end=position),
            )
        position = position.advance(current_char)
        index += 1

    return None


def split_tcl_list(text: str, start_position: Position) -> list[ListItem]:
    items: list[ListItem] = []
    index = 0
    position = start_position

    while index < len(text):
        while index < len(text) and text[index].isspace():
            position = position.advance(text[index])
            index += 1
        if index >= len(text):
            break

        item_start_position = position
        current_char = text[index]
        if current_char == '{':
            raw_text, consumed, position, content_start = _consume_braced_item(
                text[index:], position
            )
            index += consumed
            items.append(
                ListItem(
                    text=raw_text,
                    span=Span(start=item_start_position, end=position),
                    content_start=content_start,
                )
            )
            continue
        if current_char == '"':
            raw_text, consumed, position, content_start = _consume_quoted_item(
                text[index:], position
            )
            index += consumed
            items.append(
                ListItem(
                    text=raw_text,
                    span=Span(start=item_start_position, end=position),
                    content_start=content_start,
                )
            )
            continue

        item_text, consumed, position = _consume_plain_item(text[index:], position)
        index += consumed
        items.append(
            ListItem(
                text=item_text,
                span=Span(start=item_start_position, end=position),
                content_start=item_start_position,
            )
        )

    return items


def _consume_braced_item(
    text: str, start_position: Position
) -> tuple[str, int, Position, Position]:
    index = 0
    position = start_position
    position = position.advance(text[index])
    index += 1
    content_start = position
    depth = 1
    parts: list[str] = []

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            if index < len(text):
                parts.append(text[index])
                position = position.advance(text[index])
                index += 1
            continue
        if current_char == '{':
            depth += 1
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            continue
        if current_char == '}':
            depth -= 1
            if depth == 0:
                position = position.advance(current_char)
                index += 1
                return ''.join(parts), index, position, content_start
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            continue
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1

    return ''.join(parts), index, position, content_start


def _consume_quoted_item(
    text: str, start_position: Position
) -> tuple[str, int, Position, Position]:
    index = 0
    position = start_position
    position = position.advance(text[index])
    index += 1
    content_start = position
    parts: list[str] = []

    while index < len(text):
        current_char = text[index]
        if current_char == '"':
            position = position.advance(current_char)
            index += 1
            return ''.join(parts), index, position, content_start
        if current_char == '\\' and index + 1 < len(text):
            index += 1
            current_char = text[index]
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1

    return ''.join(parts), index, position, content_start


def _consume_plain_item(text: str, start_position: Position) -> tuple[str, int, Position]:
    index = 0
    position = start_position
    parts: list[str] = []
    while index < len(text) and not text[index].isspace():
        current_char = text[index]
        if current_char == '\\' and index + 1 < len(text):
            index += 1
            current_char = text[index]
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1
    return ''.join(parts), index, position
