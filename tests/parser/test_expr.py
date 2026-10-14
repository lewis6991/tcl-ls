from __future__ import annotations

import pytest

from tcl_lsp.parser.expr import parse_expr_result


@pytest.mark.parametrize(
    ('text', 'message', 'offset'),
    [
        ('', 'Expected an operand, but found the end of the expression.', 0),
        ('1 + )', 'Expected an operand, but found `)`.', 4),
        ('1 2', 'Expected an operator, but found `2`.', 2),
        ('1 ? 2 :', 'Expected an operand, but found the end of the expression.', 7),
        ('max(1,)', 'Expected an operand, but found `)`.', 6),
        ('1 + "abc', 'Unclosed string literal; expected `"`.', 4),
        ('1 + {abc', 'Unclosed braced string literal; expected `}`.', 4),
        ('1 + [puts x', 'Unclosed command substitution; expected `]`.', 4),
        ('"[puts x"', 'Unclosed command substitution; expected `]`.', 1),
    ],
)
def test_invalid_expression_explains_the_error_at_its_character(
    text: str, message: str, offset: int
) -> None:
    result = parse_expr_result(text)

    assert result.expression is None
    assert result.error is not None
    assert result.error.message == message
    assert result.error.offset == offset


@pytest.mark.parametrize('text', ['(bad)', 'bad 1 2', 'bad "unclosed', '0 && (bad)'])
def test_bare_word_error_survives_parentheses_and_later_errors(text: str) -> None:
    result = parse_expr_result(text)

    assert result.expression is None
    assert result.error is not None
    assert result.error.message == (
        'Invalid bare word `bad`: expected a number or boolean literal.'
    )
    assert result.error.offset == text.index('bad')


@pytest.mark.parametrize(
    'text',
    ['1 + 2', '(1 + 2)', '1 ? 2 : 3', 'max(1, 2)', 'max(1, min(2, 3))', '$a + 1', '"a" eq {b}'],
)
def test_valid_expression_has_no_syntax_error(text: str) -> None:
    result = parse_expr_result(text)

    assert result.expression is not None
    assert result.error is None


@pytest.mark.parametrize('text', ['$values(key) + 1', r'"\x34" +'])
def test_unmodelled_syntax_is_not_reported_as_invalid(text: str) -> None:
    result = parse_expr_result(text)

    assert result.expression is None
    assert result.error is None
