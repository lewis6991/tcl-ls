from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tcl_lsp.common import Diagnostic, Span

type TokenKind = Literal['bare_word', 'braced_word', 'quoted_word', 'separator', 'comment']


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    span: Span
    text: str


@dataclass(frozen=True, slots=True)
class LiteralText:
    span: Span
    text: str


@dataclass(frozen=True, slots=True)
class VariableSubstitution:
    span: Span
    name: str
    brace_wrapped: bool


@dataclass(frozen=True, slots=True)
class CommandSubstitution:
    span: Span
    content_span: Span
    script: Script


type WordPart = LiteralText | VariableSubstitution | CommandSubstitution


@dataclass(frozen=True, slots=True)
class BareWord:
    span: Span
    content_span: Span
    parts: tuple[WordPart, ...]
    expanded: bool = False


@dataclass(frozen=True, slots=True)
class BracedWord:
    span: Span
    content_span: Span
    text: str
    raw_text: str
    expanded: bool = False


@dataclass(frozen=True, slots=True)
class QuotedWord:
    span: Span
    content_span: Span
    parts: tuple[WordPart, ...]
    expanded: bool = False


type Word = BareWord | BracedWord | QuotedWord


@dataclass(frozen=True, slots=True)
class Command:
    span: Span
    words: tuple[Word, ...]
    leading_comments: tuple[Token, ...] = ()


@dataclass(frozen=True, slots=True)
class Script:
    span: Span
    commands: tuple[Command, ...]


@dataclass(frozen=True, slots=True)
class ParseResult:
    source_id: str
    script: Script
    tokens: tuple[Token, ...]
    diagnostics: tuple[Diagnostic, ...]
