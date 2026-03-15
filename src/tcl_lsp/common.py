from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type DiagnosticSeverity = Literal['error', 'warning', 'information', 'hint']
type SymbolKind = Literal['namespace', 'function', 'variable']


@dataclass(frozen=True, slots=True)
class Position:
    offset: int
    line: int
    character: int

    def advance(self, text: str) -> Position:
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


@dataclass(frozen=True, slots=True)
class Location:
    uri: str
    span: Span


@dataclass(frozen=True, slots=True)
class Diagnostic:
    span: Span
    severity: DiagnosticSeverity
    message: str
    source: str
    code: str


@dataclass(frozen=True, slots=True)
class DocumentSymbol:
    name: str
    kind: SymbolKind
    span: Span
    selection_span: Span
    children: tuple[DocumentSymbol, ...]


@dataclass(frozen=True, slots=True)
class HoverInfo:
    span: Span
    contents: str
