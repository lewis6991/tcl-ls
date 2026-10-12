from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class NamedType:
    name: str


@dataclass(frozen=True, slots=True)
class LiteralType:
    value: str
    kind: Literal['string', 'number']


@dataclass(frozen=True, slots=True)
class UnionType:
    members: tuple[TypeNode, ...]


@dataclass(frozen=True, slots=True)
class ListType:
    element: TypeNode


@dataclass(frozen=True, slots=True)
class GenericType:
    name: str
    arguments: tuple[TypeNode, ...]


@dataclass(frozen=True, slots=True)
class RecordType:
    fields: tuple[tuple[str, TypeNode], ...]


@dataclass(frozen=True, slots=True)
class TupleType:
    elements: tuple[TypeNode, ...]


type TypeNode = (
    NamedType | LiteralType | UnionType | ListType | GenericType | RecordType | TupleType
)


@dataclass(frozen=True, slots=True)
class TypeExpression:
    text: str
    names: tuple[str, ...]
    node: TypeNode


@dataclass(frozen=True, slots=True)
class TypeInfo:
    expression: TypeExpression
    resolved: TypeNode


@dataclass(frozen=True, slots=True)
class CallType:
    """Resolved flow input for one command, located by source offsets."""

    start: int
    end: int
    return_type: TypeInfo | None
    unpacks_tuple: bool = False


type CallTypes = tuple[CallType, ...]


def tuple_element_type(info: TypeInfo, index: int) -> TypeInfo | None:
    if not isinstance(info.resolved, TupleType):
        return None
    if index >= len(info.resolved.elements):
        # Tcl assigns an empty string when lassign runs out of list elements.
        node = LiteralType('', 'string')
        return TypeInfo(TypeExpression('""', (), node), node)
    resolved = info.resolved.elements[index]
    expression = info.expression.node
    node = expression.elements[index] if isinstance(expression, TupleType) else resolved
    return TypeInfo(TypeExpression(type_text(node), type_names(node), node), resolved)


def type_names(node: TypeNode) -> tuple[str, ...]:
    match node:
        case NamedType(name):
            return (name,)
        case LiteralType():
            return ()
        case GenericType(name, arguments):
            return tuple(dict.fromkeys((name, *(n for arg in arguments for n in type_names(arg)))))
        case ListType(element):
            return type_names(element)
        case UnionType(children) | TupleType(children):
            return tuple(dict.fromkeys(n for child in children for n in type_names(child)))
        case RecordType(fields):
            return tuple(dict.fromkeys(n for _, child in fields for n in type_names(child)))


def type_text(node: TypeNode) -> str:
    match node:
        case NamedType(name):
            return name
        case LiteralType(value, kind):
            return json.dumps(value) if kind == 'string' else value
        case UnionType(members):
            return '|'.join(type_text(member) for member in members)
        case ListType(element):
            text = type_text(element)
            return f'({text})[]' if isinstance(element, UnionType) else f'{text}[]'
        case GenericType(name, arguments):
            return f'{name}<{", ".join(type_text(arg) for arg in arguments)}>'
        case RecordType(fields):
            return (
                '{'
                + ', '.join(
                    f'{name if name.isidentifier() else json.dumps(name)}: {type_text(item)}'
                    for name, item in fields
                )
                + '}'
            )
        case TupleType(elements):
            return '[' + ', '.join(type_text(item) for item in elements) + ']'


type AliasKey = tuple[str, str]
type AliasDefinitions = tuple[tuple[str, str, TypeExpression], ...]


def alias_key(name: str, namespace: str, aliases: Mapping[AliasKey, object]) -> AliasKey | None:
    candidates = (name,) if name.startswith('::') else (f'{namespace}::{name}', f'::{name}')
    for candidate in candidates:
        prefix, _, tail = candidate.rpartition('::')
        key = ('::' + prefix.lstrip(':'), tail)
        if key in aliases:
            return key
    return None


class TypeResolver:
    """Resolve file-local aliases without expanding recursive definitions forever."""

    def __init__(self, aliases: AliasDefinitions) -> None:
        self._aliases = {
            (namespace, name): expression.node for namespace, name, expression in aliases
        }
        self._resolved: dict[AliasKey, TypeNode] = {}
        self._active: set[AliasKey] = set()

    def resolve(self, expression: TypeExpression, namespace: str) -> TypeInfo:
        try:
            node = self._resolve(expression.node, namespace)
        except RecursionError:
            node = expression.node
        return TypeInfo(expression, node)

    def _resolve(self, node: TypeNode, namespace: str) -> TypeNode:
        match node:
            case NamedType(name):
                key = alias_key(name, namespace, self._aliases)
                if key is None or key in self._active:
                    return node
                if key not in self._resolved:
                    self._active.add(key)
                    try:
                        self._resolved[key] = self._resolve(self._aliases[key], key[0])
                    finally:
                        self._active.remove(key)
                return self._resolved[key]
            case UnionType(members):
                return UnionType(tuple(self._resolve(member, namespace) for member in members))
            case ListType(element):
                return ListType(self._resolve(element, namespace))
            case GenericType(name, arguments):
                return GenericType(
                    name, tuple(self._resolve(argument, namespace) for argument in arguments)
                )
            case RecordType(fields):
                return RecordType(
                    tuple((name, self._resolve(field, namespace)) for name, field in fields)
                )
            case TupleType(elements):
                return TupleType(tuple(self._resolve(element, namespace) for element in elements))
            case LiteralType():
                return node


def literal_values(node: TypeNode) -> tuple[str, ...]:
    """Return values only when the entire type is a finite union of literals."""
    match node:
        case LiteralType(value, _):
            return (value,)
        case UnionType(members):
            values = tuple(literal_values(member) for member in members)
            if all(values):
                return tuple(dict.fromkeys(value for group in values for value in group))
        case _:
            pass
    return ()
