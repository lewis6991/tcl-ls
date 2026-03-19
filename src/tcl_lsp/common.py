from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lsprotocol import types

type DiagnosticSeverity = Literal['error', 'warning', 'information', 'hint']
type SymbolKind = Literal['namespace', 'function', 'variable']


@dataclass(frozen=True, slots=True)
class Position:
    offset: int
    line: int
    character: int

    def advance(self, text: str) -> Position:
        if not text:
            return self
        if len(text) == 1:
            offset = self.offset + 1
            if text == '\n':
                return Position(offset=offset, line=self.line + 1, character=0)
            return Position(offset=offset, line=self.line, character=self.character + 1)
        offset = self.offset
        line = self.line
        character = self.character
        for char in text:
            offset += 1
            if char == '\n':
                line += 1
                character = 0
            else:
                character += 1
        return Position(offset=offset, line=line, character=character)


@dataclass(frozen=True, slots=True)
class Span:
    start: Position
    end: Position

    def contains(self, line: int, character: int) -> bool:
        if line < self.start.line or line > self.end.line:
            return False
        if line == self.start.line and character < self.start.character:
            return False
        if line == self.end.line and character >= self.end.character:
            return False
        return True


def lsp_position(position: Position) -> types.Position:
    return types.Position(line=position.line, character=position.character)


def lsp_range(span: Span) -> types.Range:
    return types.Range(start=lsp_position(span.start), end=lsp_position(span.end))


def lsp_location(uri: str, span: Span) -> types.Location:
    return types.Location(uri=uri, range=lsp_range(span))


def offset_at_position(text: str, line: int, character: int) -> int | None:
    if line < 0 or character < 0:
        return None

    current_line = 0
    line_start = 0
    for index, char in enumerate(text):
        if current_line == line:
            break
        if char == '\n':
            current_line += 1
            line_start = index + 1
    else:
        if current_line != line:
            if line == current_line:
                line_start = len(text)
            else:
                return None

    if current_line != line:
        return None

    line_end = text.find('\n', line_start)
    if line_end < 0:
        line_end = len(text)

    if character > line_end - line_start:
        return None
    return line_start + character


@dataclass(frozen=True, slots=True)
class Diagnostic:
    span: Span
    severity: DiagnosticSeverity
    message: str
    source: str
    code: str


@dataclass(frozen=True, slots=True)
class HoverInfo:
    span: Span
    contents: str
