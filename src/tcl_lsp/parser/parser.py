from __future__ import annotations

import re
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
_BARE_WORD_PLAIN_TEXT_RUN = re.compile(r'[^ \t\r\f\n;\[$\\]+')
_BARE_WORD_PLAIN_TEXT_WITH_BRACKET_STOP_RUN = re.compile(r'[^ \t\r\f\n;\[$\\\]]+')
_COMMENT_TEXT_RUN = re.compile(r'[^\\\n]+')
_HORIZONTAL_WHITESPACE_RUN = re.compile(r'[ \t\r\f]+')
_QUOTED_WORD_PLAIN_TEXT_RUN = re.compile(r'[^"[$\\]+')
_ESCAPE_MAP = {'n': '\n', 't': '\t', 'r': '\r'}
_DOCUMENT_START_POSITION = Position(offset=0, line=0, character=0)


@dataclass(slots=True)
class _TextBuffer:
    start: Position | None
    pieces: list[str]


class Parser:
    __slots__ = ()

    def parse_document(self, path: str, text: str) -> ParseResult:
        return _ParserImplementation(
            source_id=path,
            text=text,
            start_position=_DOCUMENT_START_POSITION,
            collect_tokens=True,
        ).parse()

    def parse_embedded_script(
        self,
        source_id: str,
        text: str,
        start_position: Position,
    ) -> ParseResult:
        return _ParserImplementation(
            source_id=source_id,
            text=text,
            start_position=start_position,
            collect_tokens=True,
        ).parse()

    def parse_embedded_script_for_analysis(
        self,
        source_id: str,
        text: str,
        start_position: Position,
        *,
        diagnostics: list[Diagnostic] | None = None,
    ) -> Script:
        return _ParserImplementation(
            source_id=source_id,
            text=text,
            start_position=start_position,
            collect_tokens=False,
        ).parse_for_analysis(diagnostics)


class _ParserImplementation:
    __slots__ = (
        '_character',
        '_collect_tokens',
        '_diagnostics',
        '_index',
        '_line',
        '_offset',
        '_source_id',
        '_text',
        '_text_length',
        '_tokens',
    )

    def __init__(
        self,
        source_id: str,
        text: str,
        start_position: Position,
        *,
        collect_tokens: bool,
    ) -> None:
        self._source_id = source_id
        self._text = text
        self._text_length = len(text)
        self._index = 0
        self._offset = start_position.offset
        self._line = start_position.line
        self._character = start_position.character
        self._collect_tokens = collect_tokens
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

    def parse_for_analysis(self, diagnostics: list[Diagnostic] | None = None) -> Script:
        script = self._parse_script(stop_char=None)
        if diagnostics is not None:
            diagnostics.extend(self._diagnostics)
        return script

    def _parse_script(self, stop_char: str | None) -> Script:
        start = self._current_position()
        commands: list[Command] = []
        at_command_start = True
        pending_comments: list[Token] = []
        previous_token_was_separator = False

        while True:
            self._consume_horizontal_whitespace()
            if self._is_at_stop_char(stop_char) or self._is_eof():
                break

            current_char = self._peek()
            if current_char == '\n' or current_char == ';':
                self._record_token(
                    kind='separator',
                    start_index=self._index,
                    start_position=self._current_position(),
                )
                self._advance_char()
                if pending_comments and previous_token_was_separator:
                    pending_comments.clear()
                previous_token_was_separator = True
                at_command_start = True
                continue

            if at_command_start and current_char == '#':
                pending_comments.append(self._parse_comment())
                previous_token_was_separator = False
                at_command_start = True
                continue

            command = self._parse_command(stop_char, tuple(pending_comments))
            if command.words:
                commands.append(command)
            pending_comments.clear()
            previous_token_was_separator = False
            at_command_start = False

        return Script(span=Span(start=start, end=self._current_position()), commands=tuple(commands))

    def _parse_command(
        self, stop_char: str | None, leading_comments: tuple[Token, ...]
    ) -> Command:
        start = self._current_position()
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
        return Command(
            span=Span(start=start, end=end),
            words=tuple(words),
            leading_comments=leading_comments,
        )

    def _parse_word(self, stop_char: str | None) -> Word:
        current_char = self._peek()
        if current_char == '{':
            return self._parse_braced_word()
        if current_char == '"':
            return self._parse_quoted_word()
        return self._parse_bare_word(stop_char)

    def _parse_comment(self) -> Token:
        start_index = self._index
        start_position = self._current_position()
        text = self._text
        comment_text_match = _COMMENT_TEXT_RUN.match
        while not self._is_eof():
            comment_text_run = comment_text_match(text, self._index)
            if comment_text_run is not None:
                self._advance_plain_run(comment_text_run.end())
                continue
            if self._starts_line_continuation():
                self._consume_line_continuation()
                continue
            if text[self._index] == '\n':
                break
            self._advance_char()
        comment = Token(
            kind='comment',
            span=Span(start=start_position, end=self._current_position()),
            text=self._text[start_index : self._index],
        )
        self._append_token(comment)
        return comment

    def _parse_bare_word(self, stop_char: str | None) -> BareWord:
        start_index = self._index
        start_position = self._current_position()
        buffer = _TextBuffer(start=None, pieces=[])
        parts: list[WordPart] = []
        text = self._text
        plain_text_run = _BARE_WORD_PLAIN_TEXT_RUN
        if stop_char == ']':
            plain_text_run = _BARE_WORD_PLAIN_TEXT_WITH_BRACKET_STOP_RUN
        elif stop_char is not None:
            plain_text_run = None

        while not self._is_eof():
            if self._is_at_stop_char(stop_char):
                break
            if plain_text_run is not None:
                bare_word_text_run = plain_text_run.match(text, self._index)
                if bare_word_text_run is not None:
                    plain_text = bare_word_text_run.group(0)
                    self._append_text(buffer, plain_text)
                    self._advance_plain_run(bare_word_text_run.end())
                    continue

            current_char = text[self._index]
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
        end_position = self._current_position()
        word = BareWord(
            span=Span(start=start_position, end=end_position),
            content_span=Span(start=start_position, end=end_position),
            parts=tuple(parts),
        )
        if self._collect_tokens:
            self._append_token(
                Token(
                    kind='bare_word',
                    span=word.span,
                    text=self._text[start_index : self._index],
                )
            )
        return word

    def _parse_quoted_word(self) -> QuotedWord:
        start_index = self._index
        start_position = self._current_position()
        self._advance_char()
        content_start = self._current_position()
        buffer = _TextBuffer(start=None, pieces=[])
        parts: list[WordPart] = []
        text = self._text
        quoted_text_match = _QUOTED_WORD_PLAIN_TEXT_RUN.match

        while not self._is_eof():
            quoted_text_run = quoted_text_match(text, self._index)
            if quoted_text_run is not None:
                plain_text = quoted_text_run.group(0)
                self._append_text(buffer, plain_text)
                self._advance_text(plain_text)
                continue

            current_char = text[self._index]
            if current_char == '"':
                self._flush_buffer(buffer, parts)
                content_end = self._current_position()
                self._advance_char()
                end_position = self._current_position()
                word = QuotedWord(
                    span=Span(start=start_position, end=end_position),
                    content_span=Span(start=content_start, end=content_end),
                    parts=tuple(parts),
                )
                if self._collect_tokens:
                    self._append_token(
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
        end_position = self._current_position()
        self._add_diagnostic(
            code='unmatched-quote',
            message='Expected a closing `"` for this quoted word.',
            start=start_position,
            end=end_position,
        )
        word = QuotedWord(
            span=Span(start=start_position, end=end_position),
            content_span=Span(start=content_start, end=end_position),
            parts=tuple(parts),
        )
        if self._collect_tokens:
            self._append_token(
                Token(
                    kind='quoted_word',
                    span=word.span,
                    text=self._text[start_index : self._index],
                )
            )
        return word

    def _parse_braced_word(self) -> BracedWord:
        start_index = self._index
        start_position = self._current_position()
        self._advance_char()
        content_start = self._current_position()
        depth = 1
        text_parts: list[str] = []

        while not self._is_eof():
            next_special_index = self._next_braced_special_index()
            if next_special_index == -1:
                remaining_text = self._text[self._index :]
                text_parts.append(remaining_text)
                self._advance_text(remaining_text)
                break
            if next_special_index > self._index:
                plain_text = self._text[self._index : next_special_index]
                text_parts.append(plain_text)
                self._advance_text(plain_text)
                continue

            current_char = self._peek()
            if current_char == '\\':
                if self._starts_line_continuation():
                    self._consume_line_continuation()
                    text_parts.append(' ')
                    continue
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
                    content_end = self._current_position()
                    self._advance_char()
                    end_position = self._current_position()
                    word = BracedWord(
                        span=Span(start=start_position, end=end_position),
                        content_span=Span(start=content_start, end=content_end),
                        text=''.join(text_parts),
                        raw_text=self._text[start_index : self._index],
                    )
                    if self._collect_tokens:
                        self._append_token(
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

        end_position = self._current_position()
        self._add_diagnostic(
            code='unmatched-brace',
            message='Expected a closing `}` for this braced word.',
            start=start_position,
            end=end_position,
        )
        word = BracedWord(
            span=Span(start=start_position, end=end_position),
            content_span=Span(start=content_start, end=end_position),
            text=''.join(text_parts),
            raw_text=self._text[start_index : self._index],
        )
        if self._collect_tokens:
            self._append_token(
                Token(
                    kind='braced_word',
                    span=word.span,
                    text=self._text[start_index : self._index],
                )
            )
        return word

    def _parse_command_substitution(self) -> CommandSubstitution:
        start_position = self._current_position()
        self._advance_char()
        content_start = self._current_position()
        script = self._parse_script(stop_char=']')
        content_end = self._current_position()

        if self._is_eof() or self._peek() != ']':
            end_position = self._current_position()
            self._add_diagnostic(
                code='unmatched-bracket',
                message='Expected a closing `]` for this command substitution.',
                start=start_position,
                end=end_position,
            )
            return CommandSubstitution(
                span=Span(start=start_position, end=end_position),
                content_span=Span(start=content_start, end=content_end),
                script=script,
            )

        self._advance_char()
        end_position = self._current_position()
        return CommandSubstitution(
            span=Span(start=start_position, end=end_position),
            content_span=Span(start=content_start, end=content_end),
            script=script,
        )

    def _parse_variable_substitution(self) -> WordPart:
        start_index = self._index
        start_position = self._current_position()
        self._advance_char()
        if self._is_eof():
            return LiteralText(span=Span(start=start_position, end=self._current_position()), text='$')

        current_char = self._peek()
        if current_char == '{':
            self._advance_char()
            name_start = self._index
            while not self._is_eof() and self._peek() != '}':
                if self._peek() == '\n':
                    break
                self._advance_char()
            if self._is_eof() or self._peek() != '}':
                end_position = self._current_position()
                self._add_diagnostic(
                    code='malformed-variable',
                    message='Expected a closing `}` for this variable substitution.',
                    start=start_position,
                    end=end_position,
                )
                return LiteralText(
                    span=Span(start=start_position, end=end_position),
                    text=self._text[start_index : self._index],
                )

            name = self._text[name_start : self._index].strip()
            self._advance_char()
            if not name:
                end_position = self._current_position()
                self._add_diagnostic(
                    code='malformed-variable',
                    message='Expected a non-empty variable name inside `${...}`.',
                    start=start_position,
                    end=end_position,
                )
                return LiteralText(
                    span=Span(start=start_position, end=end_position),
                    text=self._text[start_index : self._index],
                )

            return VariableSubstitution(
                span=Span(start=start_position, end=self._current_position()),
                name=name,
                brace_wrapped=True,
            )

        if current_char not in _SIMPLE_VARIABLE_CONTINUATIONS:
            return LiteralText(span=Span(start=start_position, end=self._current_position()), text='$')

        name_start = self._index
        while not self._is_eof() and self._peek() in _SIMPLE_VARIABLE_CONTINUATIONS:
            self._advance_char()
        name = self._text[name_start : self._index]
        return VariableSubstitution(
            span=Span(start=start_position, end=self._current_position()),
            name=name,
            brace_wrapped=False,
        )

    def _append_text(self, buffer: _TextBuffer, text: str) -> None:
        if buffer.start is None:
            buffer.start = self._current_position()
        buffer.pieces.append(text)

    def _append_escape_sequence(self, buffer: _TextBuffer) -> None:
        if buffer.start is None:
            buffer.start = self._current_position()
        if self._starts_line_continuation():
            self._consume_line_continuation()
            buffer.pieces.append(' ')
            return
        self._advance_char()
        if self._is_eof():
            buffer.pieces.append('\\')
            return
        escaped_char = self._peek()
        buffer.pieces.append(_ESCAPE_MAP.get(escaped_char, escaped_char))
        self._advance_char()

    def _flush_buffer(self, buffer: _TextBuffer, parts: list[WordPart]) -> None:
        if buffer.start is None or not buffer.pieces:
            buffer.start = None
            buffer.pieces.clear()
            return
        parts.append(
            LiteralText(
                span=Span(start=buffer.start, end=self._current_position()),
                text=''.join(buffer.pieces),
            )
        )
        buffer.start = None
        buffer.pieces.clear()

    def _consume_horizontal_whitespace(self) -> None:
        whitespace_match = _HORIZONTAL_WHITESPACE_RUN.match
        text = self._text
        while not self._is_eof():
            whitespace_run = whitespace_match(text, self._index)
            if whitespace_run is not None:
                self._advance_plain_run(whitespace_run.end())
                continue
            if self._starts_line_continuation():
                self._consume_line_continuation()
                continue
            break

    def _record_token(self, kind: TokenKind, start_index: int, start_position: Position) -> None:
        if not self._collect_tokens:
            return
        current_char = self._peek()
        self._append_token(
            Token(
                kind=kind,
                span=Span(start=start_position, end=self._position_after_char(current_char)),
                text=self._text[start_index : start_index + 1],
            )
        )

    def _append_token(self, token: Token) -> None:
        if self._collect_tokens:
            self._tokens.append(token)

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
        self._offset += 1
        if current_char == '\n':
            self._line += 1
            self._character = 0
            return
        self._character += 1

    def _advance_text(self, text: str) -> None:
        if not text:
            return
        self._index += len(text)
        self._offset += len(text)
        newline_count = text.count('\n')
        if not newline_count:
            self._character += len(text)
            return
        self._line += newline_count
        self._character = len(text) - text.rfind('\n') - 1

    def _advance_plain_run(self, end_index: int) -> None:
        if end_index <= self._index:
            return
        length = end_index - self._index
        self._index = end_index
        self._offset += length
        self._character += length

    def _starts_line_continuation(self) -> bool:
        if self._is_eof() or self._peek() != '\\':
            return False
        next_index = self._index + 1
        return next_index < self._text_length and self._text[next_index] in {'\n', '\r'}

    def _consume_line_continuation(self) -> None:
        self._advance_char()
        if self._is_eof():
            return
        if self._peek() == '\r':
            self._advance_char()
            if not self._is_eof() and self._peek() == '\n':
                self._advance_char()
        elif self._peek() == '\n':
            self._advance_char()
        while not self._is_eof() and self._peek() in _HORIZONTAL_WHITESPACE:
            self._advance_char()

    def _is_at_stop_char(self, stop_char: str | None) -> bool:
        return stop_char is not None and not self._is_eof() and self._peek() == stop_char

    def _peek(self) -> str:
        return self._text[self._index]

    def _is_eof(self) -> bool:
        return self._index >= self._text_length

    def _current_position(self) -> Position:
        return Position(offset=self._offset, line=self._line, character=self._character)

    def _position_after_char(self, char: str) -> Position:
        if char == '\n':
            return Position(offset=self._offset + 1, line=self._line + 1, character=0)
        return Position(offset=self._offset + 1, line=self._line, character=self._character + 1)

    def _next_braced_special_index(self) -> int:
        text = self._text
        index = self._index
        backslash_index = text.find('\\', index)
        open_brace_index = text.find('{', index)
        close_brace_index = text.find('}', index)

        next_index = self._text_length
        for candidate in (backslash_index, open_brace_index, close_brace_index):
            if candidate != -1 and candidate < next_index:
                next_index = candidate

        if next_index == self._text_length:
            return -1
        return next_index
