from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Literal

from tcl_lsp.parser.helpers import consume_bare_variable_name_end

type Expr = (
    ExprAtom | ExprBinary | ExprCommandSubstitution | ExprFunctionCall | ExprTernary | ExprUnary
)

type _TokenKind = Literal['atom', 'command', 'comma', 'eof', 'lparen', 'operator', 'rparen']

_BAREWORD_OPERATORS = frozenset({'eq', 'ge', 'gt', 'in', 'le', 'lt', 'ne', 'ni'})
_SYMBOLIC_OPERATORS = ('||', '&&', '<=', '>=', '==', '!=', '<<', '>>', '**')
_SINGLE_CHAR_OPERATORS = frozenset(
    {'!', '%', '&', '*', '+', '-', '/', ':', '<', '?', '>', '^', '|', '~'}
)
_COMPARISON_OPERATORS = frozenset(
    {'<', '<=', '==', '!=', '>', '>=', 'eq', 'ge', 'gt', 'in', 'le', 'lt', 'ne', 'ni'}
)
_FUNCTION_NAME_OPERATORS = _BAREWORD_OPERATORS


@dataclass(frozen=True, slots=True)
class ExprAtom:
    text: str


@dataclass(frozen=True, slots=True)
class ExprCommandSubstitution:
    script_text: str


@dataclass(frozen=True, slots=True)
class ExprUnary:
    operator: str
    operand: Expr


@dataclass(frozen=True, slots=True)
class ExprBinary:
    operator: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class ExprTernary:
    condition: Expr
    true_expr: Expr
    false_expr: Expr


@dataclass(frozen=True, slots=True)
class ExprFunctionCall:
    name: str
    arguments: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class _Token:
    kind: _TokenKind
    text: str


def parse_expr(text: str) -> Expr | None:
    return _ExprParser(text).parse()


class _ExprParser:
    __slots__ = ('_current', '_failed', '_index', '_text')

    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0
        self._failed = False
        self._current = self._next_token()

    def parse(self) -> Expr | None:
        expr = self._parse_ternary()
        if expr is None or self._failed:
            return None
        if self._current.kind != 'eof':
            return None
        return expr

    def _parse_ternary(self) -> Expr | None:
        condition = self._parse_logical_or()
        if condition is None:
            return None
        if not self._current_is_operator('?'):
            return condition

        self._advance()
        true_expr = self._parse_ternary()
        if true_expr is None or not self._current_is_operator(':'):
            return None
        self._advance()
        false_expr = self._parse_ternary()
        if false_expr is None:
            return None
        return ExprTernary(condition, true_expr, false_expr)

    def _parse_logical_or(self) -> Expr | None:
        return self._parse_left_associative(self._parse_logical_and, {'||'})

    def _parse_logical_and(self) -> Expr | None:
        return self._parse_left_associative(self._parse_bitwise_or, {'&&'})

    def _parse_bitwise_or(self) -> Expr | None:
        return self._parse_left_associative(self._parse_bitwise_xor, {'|'})

    def _parse_bitwise_xor(self) -> Expr | None:
        return self._parse_left_associative(self._parse_bitwise_and, {'^'})

    def _parse_bitwise_and(self) -> Expr | None:
        return self._parse_left_associative(self._parse_comparison, {'&'})

    def _parse_comparison(self) -> Expr | None:
        return self._parse_left_associative(self._parse_shift, _COMPARISON_OPERATORS)

    def _parse_shift(self) -> Expr | None:
        return self._parse_left_associative(self._parse_additive, {'<<', '>>'})

    def _parse_additive(self) -> Expr | None:
        return self._parse_left_associative(self._parse_multiplicative, {'+', '-'})

    def _parse_multiplicative(self) -> Expr | None:
        return self._parse_left_associative(self._parse_power, {'*', '/', '%'})

    def _parse_power(self) -> Expr | None:
        expr = self._parse_unary()
        if expr is None or not self._current_is_operator('**'):
            return expr

        operator = self._current.text
        self._advance()
        right = self._parse_power()
        if right is None:
            return None
        return ExprBinary(operator, expr, right)

    def _parse_unary(self) -> Expr | None:
        if not self._current_is_operator('!', '+', '-', '~'):
            return self._parse_postfix()

        operator = self._current.text
        self._advance()
        operand = self._parse_unary()
        if operand is None:
            return None
        return ExprUnary(operator, operand)

    def _parse_postfix(self) -> Expr | None:
        expr = self._parse_primary()
        while isinstance(expr, ExprAtom):
            if self._current.kind != 'lparen' or not _is_function_name(expr.text):
                break
            expr = self._parse_function_call(expr.text)
            if expr is None:
                return None
        return expr

    def _parse_primary(self) -> Expr | None:
        if self._current_is_kind('atom'):
            expr = ExprAtom(self._current.text)
            self._advance()
            return expr
        if self._current_is_kind('command'):
            expr = ExprCommandSubstitution(self._current.text)
            self._advance()
            return expr
        if not self._current_is_kind('lparen'):
            return None

        self._advance()
        expr = self._parse_ternary()
        if expr is None or not self._current_is_kind('rparen'):
            return None
        self._advance()
        return expr

    def _parse_function_call(self, name: str) -> Expr | None:
        if not self._current_is_kind('lparen'):
            return None

        self._advance()
        args: list[Expr] = []
        if not self._current_is_kind('rparen'):
            while True:
                arg = self._parse_ternary()
                if arg is None:
                    return None
                args.append(arg)
                if not self._current_is_kind('comma'):
                    break
                self._advance()

        if not self._current_is_kind('rparen'):
            return None
        self._advance()
        return ExprFunctionCall(name, tuple(args))

    def _parse_left_associative(
        self,
        operand_parser: Callable[[], Expr | None],
        operators: Collection[str],
    ) -> Expr | None:
        expr = operand_parser()
        if expr is None:
            return None

        while self._current.kind == 'operator' and self._current.text in operators:
            operator = self._current.text
            self._advance()
            right = operand_parser()
            if right is None:
                return None
            expr = ExprBinary(operator, expr, right)

        return expr

    def _current_is_operator(self, *operators: str) -> bool:
        return self._current.kind == 'operator' and self._current.text in operators

    def _current_is_kind(self, kind: _TokenKind) -> bool:
        return self._current.kind == kind

    def _advance(self) -> None:
        self._current = self._next_token()

    def _next_token(self) -> _Token:
        self._skip_trivia()
        if self._index >= len(self._text):
            return _Token('eof', '')

        current_char = self._text[self._index]
        if current_char == '(':
            self._index += 1
            return _Token('lparen', '(')
        if current_char == ')':
            self._index += 1
            return _Token('rparen', ')')
        if current_char == ',':
            self._index += 1
            return _Token('comma', ',')
        if current_char == '[':
            token = self._command_token()
            if token is not None or self._failed:
                if token is None:
                    return _Token('eof', '')
                return token
        if current_char == '"':
            token = self._quoted_atom_token()
            if token is not None or self._failed:
                if token is None:
                    return _Token('eof', '')
                return token
        if current_char == '{':
            token = self._braced_atom_token()
            if token is not None or self._failed:
                if token is None:
                    return _Token('eof', '')
                return token

        for operator in _SYMBOLIC_OPERATORS:
            if self._text.startswith(operator, self._index):
                self._index += len(operator)
                return _Token('operator', operator)

        if current_char in _SINGLE_CHAR_OPERATORS:
            self._index += 1
            return _Token('operator', current_char)

        return self._bare_atom_token()

    def _skip_trivia(self) -> None:
        while self._index < len(self._text):
            current_char = self._text[self._index]
            if current_char.isspace():
                self._index += 1
                continue
            if current_char == '#':
                while self._index < len(self._text) and self._text[self._index] != '\n':
                    self._index += 1
                continue
            break

    def _quoted_atom_token(self) -> _Token | None:
        index = self._index + 1
        pieces: list[str] = []

        while index < len(self._text):
            current_char = self._text[index]
            if current_char == '"':
                self._index = index + 1
                return _Token('atom', ''.join(pieces))
            if current_char == '[':
                substitution = _consume_command_substitution(self._text, index)
                if substitution is None:
                    self._failed = True
                    self._index = len(self._text)
                    return None
                _, end_index = substitution
                pieces.append(self._text[index:end_index])
                index = end_index
                continue
            if current_char == '\\' and index + 1 < len(self._text):
                index += 1
                current_char = self._text[index]
            pieces.append(current_char)
            index += 1

        self._failed = True
        self._index = len(self._text)
        return None

    def _braced_atom_token(self) -> _Token | None:
        atom = _consume_braced_atom(self._text, self._index)
        if atom is None:
            self._failed = True
            self._index = len(self._text)
            return None

        text, end_index = atom
        self._index = end_index
        return _Token('atom', text)

    def _command_token(self) -> _Token | None:
        substitution = _consume_command_substitution(self._text, self._index)
        if substitution is None:
            self._failed = True
            self._index = len(self._text)
            return None

        script_text, end_index = substitution
        self._index = end_index
        return _Token('command', script_text)

    def _bare_atom_token(self) -> _Token:
        pieces: list[str] = []
        while self._index < len(self._text):
            current_char = self._text[self._index]
            if current_char.isspace() or current_char in {'(', ')', ',', '[', '{', '"'}:
                break
            if any(
                self._text.startswith(operator, self._index) for operator in _SYMBOLIC_OPERATORS
            ):
                break
            if current_char in _SINGLE_CHAR_OPERATORS:
                break
            if current_char == '\\' and self._index + 1 < len(self._text):
                self._index += 1
                current_char = self._text[self._index]
            pieces.append(current_char)
            self._index += 1

        text = ''.join(pieces)
        if text in _BAREWORD_OPERATORS:
            return _Token('operator', text)
        return _Token('atom', text)


def _consume_braced_atom(text: str, start_index: int) -> tuple[str, int] | None:
    index = start_index + 1
    depth = 1
    pieces: list[str] = []

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            pieces.append(current_char)
            index += 1
            if index < len(text):
                pieces.append(text[index])
                index += 1
            continue
        if current_char == '{':
            depth += 1
            pieces.append(current_char)
            index += 1
            continue
        if current_char == '}':
            depth -= 1
            if depth == 0:
                return ''.join(pieces), index + 1
            pieces.append(current_char)
            index += 1
            continue
        pieces.append(current_char)
        index += 1

    return None


def _consume_command_substitution(text: str, start_index: int) -> tuple[str, int] | None:
    index = start_index + 1
    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            index += 2
            continue
        if current_char == '{':
            braced_atom = _consume_braced_atom(text, index)
            if braced_atom is None:
                return None
            _, index = braced_atom
            continue
        if current_char == '"':
            quoted_atom = _consume_quoted_section(text, index)
            if quoted_atom is None:
                return None
            index = quoted_atom
            continue
        if current_char == '[':
            nested = _consume_command_substitution(text, index)
            if nested is None:
                return None
            _, index = nested
            continue
        if current_char == ']':
            return text[start_index + 1 : index], index + 1
        index += 1

    return None


def _consume_quoted_section(text: str, start_index: int) -> int | None:
    index = start_index + 1
    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            index += 2
            continue
        if current_char == '[':
            nested = _consume_command_substitution(text, index)
            if nested is None:
                return None
            _, index = nested
            continue
        if current_char == '"':
            return index + 1
        index += 1
    return None


def _is_function_name(name: str) -> bool:
    if not name or name in _FUNCTION_NAME_OPERATORS:
        return False
    return consume_bare_variable_name_end(name, 0) == len(name)
