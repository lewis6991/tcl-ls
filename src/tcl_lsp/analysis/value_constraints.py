"""Constraints on Tcl values, independent of their cached object representations.

None means unproved. It never means that a string is incompatible with a
numeric or list operation. Conversion checks use Tcl's spelling rules rather
than Python's more permissive numeric and truth conversions.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.types import (
    GenericType,
    ListType,
    LiteralType,
    NamedType,
    RecordType,
    TupleType,
    TypeExpression,
    TypeInfo,
    TypeNode,
    UnionType,
    type_names,
    type_text,
)
from tcl_lsp.common import Position

type Interpretation = Literal['integer', 'number', 'truth', 'list']

_INTEGER = re.compile(r'[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[0-9]+)\Z')
_FLOAT = re.compile(
    r'[+-]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
    r'|[0-9]+[eE][+-]?[0-9]+|inf(?:inity)?|nan)\Z',
    re.IGNORECASE,
)
_NEW_NUMERIC = re.compile(
    r'[+-]?(?:0[dD][0-9_]+|[0-9][0-9a-fA-FxXbBoO._eE+-]*_[0-9a-fA-F._eE+-]*)\Z'
)
_ZERO = Position(0, 0, 0)
_VALIDATION_GUARD = re.compile(
    r'\s*(?:::)?string\s+is\s+(entier|integer|double)\s+-strict\s+'
    r'\$(?:\{([\w:]+)\}|([\w:]+))\s*'
)


def validation_guard(text: str) -> tuple[str, TypeInfo] | None:
    guard = _VALIDATION_GUARD.fullmatch(text)
    if guard is None:
        return None
    node = NamedType('number' if guard[1] == 'double' else 'integer')
    return guard[2] or guard[3], constraint_info(node)


def integer_value(text: str) -> int | None:
    text = text.strip()
    if not _INTEGER.fullmatch(text):
        return None
    unsigned = text.lstrip('+-')
    base = {'x': 16, 'b': 2, 'o': 8}.get(unsigned[1:2].lower())
    if base is not None:
        digits = unsigned[2:]
    elif len(unsigned) > 1 and unsigned.startswith('0'):
        # Tcl 8 and Tcl 9 differ for legacy octal. Do not infer a value
        # for a version-dependent spelling without a configured Tcl target.
        if any(char != '0' for char in unsigned):
            return None
        base, digits = 10, unsigned
    else:
        base, digits = 10, unsigned
    try:
        result = int(digits, base)
    except ValueError:
        # Python can limit the number of decimal digits; Tcl has bignums.
        return None
    return -result if text.startswith('-') else result


def number_value(text: str) -> int | float | None:
    integer = integer_value(text)
    if integer is not None:
        return integer
    text = text.strip()
    if not _FLOAT.fullmatch(text):
        return None
    value = float(text)
    return None if math.isnan(value) else value


def truth_value(text: str) -> bool | None:
    number = number_value(text)
    if number is not None:
        return number != 0
    text = text.lower()
    # Tcl permits unambiguous abbreviations, such as "tr" and "of".
    choices = {
        result
        for word, result in (
            ('true', True),
            ('yes', True),
            ('on', True),
            ('false', False),
            ('no', False),
            ('off', False),
        )
        if text and word.startswith(text)
    }
    return next(iter(choices)) if len(choices) == 1 else None


def numeric_or_string_equal(left: str, right: str) -> bool | None:
    left_number, right_number = number_value(left), number_value(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    if literal_accepts(left, 'number') is False and literal_accepts(right, 'number') is False:
        return left == right
    # Tcl may canonicalize the numeric operand in a mixed comparison.
    return None


def literal_accepts(value: str, interpretation: Interpretation) -> bool | None:
    if interpretation == 'list':
        try:
            split_tcl_list(value, _ZERO, strict=True)
        except ValueError:
            return False
        return True
    if interpretation == 'truth' and truth_value(value) is not None:
        return True
    if interpretation == 'number' and number_value(value) is not None:
        return True
    if interpretation == 'integer' and integer_value(value) is not None:
        return True
    text = value.strip()
    if (
        _INTEGER.fullmatch(text)
        or _NEW_NUMERIC.fullmatch(text)
        or text.lstrip('+-').lower() == 'nan'
    ):
        # A large bignum or a spelling with version-dependent conversion.
        return None
    return False


def alternatives(node: TypeNode | None) -> tuple[TypeNode | None, ...]:
    if isinstance(node, UnionType):
        return tuple(member for child in node.members for member in alternatives(child))
    return (node,)


def union_nodes(nodes: tuple[TypeNode, ...]) -> TypeNode:
    members = tuple(dict.fromkeys(member for node in nodes for member in alternatives(node)))
    # All inputs are non-None, so their alternatives are also non-None.
    known = tuple(member for member in members if member is not None)
    return known[0] if len(known) == 1 else UnionType(known)


def constraint_info(node: TypeNode) -> TypeInfo:
    return TypeInfo(TypeExpression(type_text(node), type_names(node), node), node)


def value_constraint(values: tuple[str, ...], info: TypeInfo | None) -> TypeNode | None:
    if values:
        return union_nodes(tuple(LiteralType(value, 'string') for value in values))
    return info.resolved if info else None


def accepts(node: TypeNode | None, interpretation: Interpretation) -> bool | None:
    match node:
        case LiteralType(value, _):
            return literal_accepts(value, interpretation)
        case NamedType('integer' | 'entier'):
            return True
        case NamedType('number' | 'float' | 'double'):
            return True if interpretation in {'number', 'truth', 'list'} else None
        case NamedType('list' | 'dict') | ListType() | TupleType() | RecordType():
            return True if interpretation == 'list' else None
        case GenericType('list' | 'dict', _):
            return True if interpretation == 'list' else None
        case _:
            return None


def rejected_alternatives(
    node: TypeNode | None, interpretation: Interpretation
) -> tuple[tuple[TypeNode, ...], bool]:
    members = alternatives(node)
    rejected = tuple(
        member
        for member in members
        if member is not None and accepts(member, interpretation) is False
    )
    return rejected, bool(rejected) and len(rejected) == len(members)


def literal_matches(value: str, constraint: TypeNode) -> bool | None:
    """Check an assignment contract; unsupported names remain unproved."""
    match constraint:
        case UnionType(members):
            results = tuple(literal_matches(value, member) for member in members)
            return True if True in results else None if None in results else False
        case LiteralType(expected, _):
            return value == expected
        case NamedType('string' | 'any'):
            return True
        case NamedType('integer' | 'entier'):
            return literal_accepts(value, 'integer')
        case NamedType('number' | 'float' | 'double'):
            return literal_accepts(value, 'number')
        case NamedType('list'):
            return literal_accepts(value, 'list')
        case ListType(element):
            if literal_accepts(value, 'list') is False:
                return False
            # The source-list parser retains locations, not full backslash
            # substitution. Avoid a claim about elements with escapes.
            if '\\' in value:
                return None
            results = tuple(
                literal_matches(item.text, element) for item in split_tcl_list(value, _ZERO)
            )
            return False if False in results else None if None in results else True
        case _:
            return None
