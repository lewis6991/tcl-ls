from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.parser.model import (
    BareWord,
    BracedWord,
    Command,
    CommandSubstitution,
    LiteralText,
    ParseResult,
    QuotedWord,
    Script,
    Token,
    TokenKind,
    VariableSubstitution,
    Word,
    WordPart,
)

_HORIZONTAL_WHITESPACE = {' ', '\t', '\r', '\f'}
_WORD_DELIMITERS = _HORIZONTAL_WHITESPACE | {'\n', ';'}
_SIMPLE_VARIABLE_CONTINUATIONS = set(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:'
)


@dataclass(slots=True)
class _TextBuffer:
    start: Position | None
    pieces: list[str]


class Parser:
    def parse_document(self, path: str, text: str) -> ParseResult:
        implementation = _ParserImplementation(
            source_id=path,
            text=text,
            start_position=Position(offset=0, line=0, character=0),
        )
        return implementation.parse()

    def parse_embedded_script(
        self, source_id: str, text: str, start_position: Position
    ) -> ParseResult:
        implementation = _ParserImplementation(
            source_id=source_id,
            text=text,
            start_position=start_position,
        )
        return implementation.parse()


class _ParserImplementation:
    def __init__(self, source_id: str, text: str, start_position: Position) -> None:
        self._source_id = source_id
        self._text = text
        self._index = 0
        self._position = start_position
        self._tokens: list[Token] = []
        self._diagnostics: list[Diagnostic] = []

    def parse(self) -> ParseResult:
        script = self._parse_script(stop_char=None)
        return ParseResult(
            source_id=self._source_id,
            script=script,
            tokens=tuple(self._tokens),
            diagnostics=tuple(self._diagnostics),
        )

    def _parse_script(self, stop_char: str | None) -> Script:
        start = self._position
        commands: list[Command] = []
        at_command_start = True

        while True:
            self._consume_horizontal_whitespace()
            if self._is_at_stop_char(stop_char) or self._is_eof():
                break

            current_char = self._peek()
            if current_char == '\n' or current_char == ';':
                self._record_token(
                    kind='separator', start_index=self._index, start_position=self._position
                )
                self._advance_char()
                at_command_start = True
                continue

            if at_command_start and current_char == '#':
                self._parse_comment()
                at_command_start = True
                continue

            command = self._parse_command(stop_char)
            if command.words:
                commands.append(command)
            at_command_start = False

        return Script(span=Span(start=start, end=self._position), commands=tuple(commands))

    def _parse_command(self, stop_char: str | None) -> Command:
        start = self._position
        words: list[Word] = []

        while True:
            self._consume_horizontal_whitespace()
            if self._is_eof() or self._is_at_stop_char(stop_char):
                break
            current_char = self._peek()
            if current_char == '\n' or current_char == ';':
                break

            words.append(self._parse_word(stop_char))

            self._consume_horizontal_whitespace()
            if self._is_eof() or self._is_at_stop_char(stop_char):
                break
            current_char = self._peek()
            if current_char == '\n' or current_char == ';':
                break

        end = words[-1].span.end if words else start
        return Command(span=Span(start=start, end=end), words=tuple(words))

    def _parse_word(self, stop_char: str | None) -> Word:
        current_char = self._peek()
        if current_char == '{':
            return self._parse_braced_word()
        if current_char == '"':
            return self._parse_quoted_word()
        return self._parse_bare_word(stop_char)

    def _parse_comment(self) -> None:
        start_index = self._index
        start_position = self._position
        while not self._is_eof() and self._peek() != '\n':
            self._advance_char()
        self._tokens.append(
            Token(
                kind='comment',
                span=Span(start=start_position, end=self._position),
                text=self._text[start_index : self._index],
            )
        )

    def _parse_bare_word(self, stop_char: str | None) -> BareWord:
        start_index = self._index
        start_position = self._position
        buffer = _TextBuffer(start=None, pieces=[])
        parts: list[WordPart] = []

        while not self._is_eof():
            if self._is_at_stop_char(stop_char):
                break
            current_char = self._peek()
            if current_char in _WORD_DELIMITERS:
                break
            if current_char == '[':
                self._flush_buffer(buffer, parts)
                parts.append(self._parse_command_substitution())
                continue
            if current_char == '$':
                self._flush_buffer(buffer, parts)
                parts.append(self._parse_variable_substitution())
                continue
            if current_char == '\\':
                self._append_escape_sequence(buffer)
                continue
            self._append_text(buffer, current_char)
            self._advance_char()

        self._flush_buffer(buffer, parts)
        word = BareWord(
            span=Span(start=start_position, end=self._position),
            content_span=Span(start=start_position, end=self._position),
            parts=tuple(parts),
        )
        self._tokens.append(
            Token(
                kind='bare_word',
                span=word.span,
                text=self._text[start_index : self._index],
            )
        )
        return word

    def _parse_quoted_word(self) -> QuotedWord:
        start_index = self._index
        start_position = self._position
        self._advance_char()
        content_start = self._position
        buffer = _TextBuffer(start=None, pieces=[])
        parts: list[WordPart] = []

        while not self._is_eof():
            current_char = self._peek()
            if current_char == '"':
                self._flush_buffer(buffer, parts)
                content_end = self._position
                self._advance_char()
                word = QuotedWord(
                    span=Span(start=start_position, end=self._position),
                    content_span=Span(start=content_start, end=content_end),
                    parts=tuple(parts),
                )
                self._tokens.append(
                    Token(
                        kind='quoted_word',
                        span=word.span,
                        text=self._text[start_index : self._index],
                    )
                )
                return word
            if current_char == '[':
                self._flush_buffer(buffer, parts)
                parts.append(self._parse_command_substitution())
                continue
            if current_char == '$':
                self._flush_buffer(buffer, parts)
                parts.append(self._parse_variable_substitution())
                continue
            if current_char == '\\':
                self._append_escape_sequence(buffer)
                continue
            self._append_text(buffer, current_char)
            self._advance_char()

        self._flush_buffer(buffer, parts)
        self._add_diagnostic(
            code='unmatched-quote',
            message='Expected a closing `"` for this quoted word.',
            start=start_position,
            end=self._position,
        )
        word = QuotedWord(
            span=Span(start=start_position, end=self._position),
            content_span=Span(start=content_start, end=self._position),
            parts=tuple(parts),
        )
        self._tokens.append(
            Token(
                kind='quoted_word',
                span=word.span,
                text=self._text[start_index : self._index],
            )
        )
        return word

    def _parse_braced_word(self) -> BracedWord:
        start_index = self._index
        start_position = self._position
        self._advance_char()
        content_start = self._position
        depth = 1
        text_parts: list[str] = []

        while not self._is_eof():
            current_char = self._peek()
            if current_char == '\\':
                text_parts.append(current_char)
                self._advance_char()
                if not self._is_eof():
                    text_parts.append(self._peek())
                    self._advance_char()
                continue
            if current_char == '{':
                depth += 1
                text_parts.append(current_char)
                self._advance_char()
                continue
            if current_char == '}':
                depth -= 1
                if depth == 0:
                    content_end = self._position
                    self._advance_char()
                    word = BracedWord(
                        span=Span(start=start_position, end=self._position),
                        content_span=Span(start=content_start, end=content_end),
                        text=''.join(text_parts),
                    )
                    self._tokens.append(
                        Token(
                            kind='braced_word',
                            span=word.span,
                            text=self._text[start_index : self._index],
                        )
                    )
                    return word
                text_parts.append(current_char)
                self._advance_char()
                continue

            text_parts.append(current_char)
            self._advance_char()

        self._add_diagnostic(
            code='unmatched-brace',
            message='Expected a closing `}` for this braced word.',
            start=start_position,
            end=self._position,
        )
        word = BracedWord(
            span=Span(start=start_position, end=self._position),
            content_span=Span(start=content_start, end=self._position),
            text=''.join(text_parts),
        )
        self._tokens.append(
            Token(
                kind='braced_word',
                span=word.span,
                text=self._text[start_index : self._index],
            )
        )
        return word

    def _parse_command_substitution(self) -> CommandSubstitution:
        start_position = self._position
        self._advance_char()
        content_start = self._position
        script = self._parse_script(stop_char=']')
        content_end = self._position

        if self._is_eof() or self._peek() != ']':
            self._add_diagnostic(
                code='unmatched-bracket',
                message='Expected a closing `]` for this command substitution.',
                start=start_position,
                end=self._position,
            )
            return CommandSubstitution(
                span=Span(start=start_position, end=self._position),
                content_span=Span(start=content_start, end=content_end),
                script=script,
            )

        self._advance_char()
        return CommandSubstitution(
            span=Span(start=start_position, end=self._position),
            content_span=Span(start=content_start, end=content_end),
            script=script,
        )

    def _parse_variable_substitution(self) -> WordPart:
        start_index = self._index
        start_position = self._position
        self._advance_char()
        if self._is_eof():
            self._add_diagnostic(
                code='malformed-variable',
                message='Expected a variable name after `$`.',
                start=start_position,
                end=self._position,
            )
            return LiteralText(span=Span(start=start_position, end=self._position), text='$')

        current_char = self._peek()
        if current_char == '{':
            self._advance_char()
            name_start = self._index
            while not self._is_eof() and self._peek() != '}':
                if self._peek() == '\n':
                    break
                self._advance_char()
            if self._is_eof() or self._peek() != '}':
                self._add_diagnostic(
                    code='malformed-variable',
                    message='Expected a closing `}` for this variable substitution.',
                    start=start_position,
                    end=self._position,
                )
                return LiteralText(
                    span=Span(start=start_position, end=self._position),
                    text=self._text[start_index : self._index],
                )

            name = self._text[name_start : self._index].strip()
            self._advance_char()
            if not name:
                self._add_diagnostic(
                    code='malformed-variable',
                    message='Expected a non-empty variable name inside `${...}`.',
                    start=start_position,
                    end=self._position,
                )
                return LiteralText(
                    span=Span(start=start_position, end=self._position),
                    text=self._text[start_index : self._index],
                )

            return VariableSubstitution(
                span=Span(start=start_position, end=self._position),
                name=name,
                brace_wrapped=True,
            )

        if current_char not in _SIMPLE_VARIABLE_CONTINUATIONS:
            self._add_diagnostic(
                code='malformed-variable',
                message='Expected a Tcl variable name after `$`.',
                start=start_position,
                end=self._position,
            )
            return LiteralText(span=Span(start=start_position, end=self._position), text='$')

        name_start = self._index
        while not self._is_eof() and self._peek() in _SIMPLE_VARIABLE_CONTINUATIONS:
            self._advance_char()
        name = self._text[name_start : self._index]
        return VariableSubstitution(
            span=Span(start=start_position, end=self._position),
            name=name,
            brace_wrapped=False,
        )

    def _append_text(self, buffer: _TextBuffer, text: str) -> None:
        if buffer.start is None:
            buffer.start = self._position
        buffer.pieces.append(text)

    def _append_escape_sequence(self, buffer: _TextBuffer) -> None:
        if buffer.start is None:
            buffer.start = self._position
        self._advance_char()
        if self._is_eof():
            buffer.pieces.append('\\')
            return
        escaped_char = self._peek()
        escape_map = {'n': '\n', 't': '\t', 'r': '\r'}
        buffer.pieces.append(escape_map.get(escaped_char, escaped_char))
        self._advance_char()

    def _flush_buffer(self, buffer: _TextBuffer, parts: list[WordPart]) -> None:
        if buffer.start is None or not buffer.pieces:
            buffer.start = None
            buffer.pieces.clear()
            return
        parts.append(
            LiteralText(
                span=Span(start=buffer.start, end=self._position),
                text=''.join(buffer.pieces),
            )
        )
        buffer.start = None
        buffer.pieces.clear()

    def _consume_horizontal_whitespace(self) -> None:
        while not self._is_eof() and self._peek() in _HORIZONTAL_WHITESPACE:
            self._advance_char()

    def _record_token(self, kind: TokenKind, start_index: int, start_position: Position) -> None:
        self._tokens.append(
            Token(
                kind=kind,
                span=Span(start=start_position, end=self._position.advance(self._peek())),
                text=self._text[start_index : start_index + 1],
            )
        )

    def _add_diagnostic(self, code: str, message: str, start: Position, end: Position) -> None:
        self._diagnostics.append(
            Diagnostic(
                span=Span(start=start, end=end),
                severity='error',
                message=message,
                source='parser',
                code=code,
            )
        )

    def _advance_char(self) -> None:
        current_char = self._text[self._index]
        self._index += 1
        self._position = self._position.advance(current_char)

    def _is_at_stop_char(self, stop_char: str | None) -> bool:
        return stop_char is not None and not self._is_eof() and self._peek() == stop_char

    def _peek(self) -> str:
        return self._text[self._index]

    def _is_eof(self) -> bool:
        return self._index >= len(self._text)
