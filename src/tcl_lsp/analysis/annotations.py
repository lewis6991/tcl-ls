from __future__ import annotations

import ast
import re
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from tcl_lsp.analysis.types import (
    GenericType,
    ListType,
    LiteralType,
    NamedType,
    RecordType,
    TupleType,
    TypeExpression,
    TypeNode,
    UnionType,
    alias_key,
)
from tcl_lsp.common import Span

if TYPE_CHECKING:
    from tcl_lsp.analysis.model import ParameterDecl, ProcDecl

type AnnotationTokenKind = Literal[
    'keyword', 'type', 'parameter', 'property', 'string', 'number', 'operator'
]

_NAME = re.compile(r'(?:::)?[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*')
_STRING = re.compile(r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')
_TAG = re.compile(r'\s*#?\s*@(alias|param|return|type)\b')


@dataclass(frozen=True, slots=True)
class AnnotationToken:
    start: int
    end: int
    kind: AnnotationTokenKind
    declaration: bool = False


@dataclass(frozen=True, slots=True)
class Annotation:
    tag: str
    name: str | None
    type: TypeExpression | None
    description: str | None
    tokens: tuple[AnnotationToken, ...]


@dataclass(frozen=True, slots=True)
class TypeAlias:
    namespace: str
    name: str
    type: TypeExpression
    description: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class CommentAnnotation:
    span: Span
    namespace: str
    annotation: Annotation


@dataclass(frozen=True, slots=True)
class ProcedureAnnotations:
    summary: str | None = None
    parameters: tuple[Annotation, ...] = ()
    returns: Annotation | None = None

    def parameter(self, name: str) -> Annotation | None:
        return next((item for item in self.parameters if item.name == name), None)


class _TypeParser:
    """Read a type prefix and keep source offsets for semantic highlighting."""

    def __init__(self, text: str, start: int) -> None:
        self.text = text
        self.offset = start
        self.tokens: list[AnnotationToken] = []

    def _space(self) -> None:
        while self.offset < len(self.text) and self.text[self.offset].isspace():
            self.offset += 1

    def _take(self, value: str) -> bool:
        start = self.offset
        self._space()
        if self.text.startswith(value, self.offset):
            self.tokens.append(AnnotationToken(self.offset, self.offset + len(value), 'operator'))
            self.offset += len(value)
            return True
        self.offset = start
        return False

    def _expect(self, value: str) -> None:
        if not self._take(value):
            raise ValueError('Incomplete type expression')

    def _atom(self, pattern: re.Pattern[str], kind: AnnotationTokenKind) -> bool:
        self._space()
        match = pattern.match(self.text, self.offset)
        if match is None:
            return False
        self.tokens.append(AnnotationToken(match.start(), match.end(), kind))
        self.offset = match.end()
        return True

    def expression(self) -> TypeNode:
        members = [self._primary()]
        while self._take('|'):
            members.append(self._primary())
        return members[0] if len(members) == 1 else UnionType(tuple(members))

    def _primary(self) -> TypeNode:
        node: TypeNode
        if self._take('('):
            node = self.expression()
            self._expect(')')
        elif self._take('['):
            node = TupleType(self._sequence(']'))
        elif self._take('{'):
            fields: list[tuple[str, TypeNode]] = []
            if not self._take('}'):
                while True:
                    if not (self._atom(_NAME, 'property') or self._atom(_STRING, 'property')):
                        raise ValueError('Expected record field')
                    token = self.tokens[-1]
                    name = self.text[token.start : token.end]
                    if name.startswith(('"', "'")):
                        name = _string_value(name)
                    self._expect(':')
                    fields.append((name, self.expression()))
                    if self._take('}'):
                        break
                    self._expect(',')
            node = RecordType(tuple(fields))
        elif self._atom(_STRING, 'string'):
            token = self.tokens[-1]
            node = LiteralType(_string_value(self.text[token.start : token.end]), 'string')
        elif self._atom(_NUMBER, 'number'):
            token = self.tokens[-1]
            node = LiteralType(self.text[token.start : token.end], 'number')
        elif self._atom(_NAME, 'type'):
            token = self.tokens[-1]
            name = self.text[token.start : token.end]
            node = NamedType(name)
            if self._take('<'):
                arguments = [self.expression()]
                while self._take(','):
                    arguments.append(self.expression())
                self._expect('>')
                node = GenericType(name, tuple(arguments))
        else:
            raise ValueError('Expected type')
        while self._take('[]'):
            node = ListType(node)
        return node

    def _sequence(self, end: str) -> tuple[TypeNode, ...]:
        if self._take(end):
            return ()
        elements = [self.expression()]
        while self._take(','):
            elements.append(self.expression())
        self._expect(end)
        return tuple(elements)


def _string_value(text: str) -> str:
    value: object = ast.literal_eval(text)
    if not isinstance(value, str):
        raise ValueError('Expected string literal')
    return value


def parse_annotation(text: str) -> Annotation | None:
    """Parse one comment line, after removal of its Tcl comment marker."""
    match = _TAG.match(text)
    if match is None:
        return None
    tag = match[1]
    tokens = [AnnotationToken(match.start(1) - 1, match.end(), 'keyword')]
    offset = match.end()
    if offset < len(text) and not text[offset].isspace():
        return None
    name = None
    if tag in {'param', 'alias'}:
        name_match = _NAME.match(text, offset + len(text[offset:]) - len(text[offset:].lstrip()))
        if name_match is None:
            return None
        name = name_match[0]
        tokens.append(
            AnnotationToken(
                name_match.start(),
                name_match.end(),
                'parameter' if tag == 'param' else 'type',
                tag == 'alias',
            )
        )
        offset = name_match.end()
    start = offset + len(text[offset:]) - len(text[offset:].lstrip())
    if start == offset:
        return None
    parser = _TypeParser(text, start)
    try:
        node = parser.expression()
    except (ValueError, SyntaxError, RecursionError):
        return None
    end = parser.offset
    if end < len(text) and not text[end].isspace():
        return None
    tokens.extend(parser.tokens)
    names = tuple(
        dict.fromkeys(
            text[token.start : token.end] for token in parser.tokens if token.kind == 'type'
        )
    )
    return Annotation(
        tag,
        name,
        TypeExpression(text[start:end], names, node),
        text[end:].strip() or None,
        tuple(tokens),
    )


def parse_procedure_annotations(documentation: str | None) -> ProcedureAnnotations:
    if documentation is None:
        return ProcedureAnnotations()
    summary: list[str] = []
    annotations: list[Annotation] = []
    continuing = False
    for line in documentation.splitlines():
        annotation = parse_annotation(line)
        if annotation is not None and annotation.tag in {'param', 'return'}:
            annotations.append(annotation)
            continuing = True
        elif (
            continuing and line[:1].isspace() and line.strip() and not line.lstrip().startswith('@')
        ):
            previous = annotations[-1]
            description = '\n'.join(filter(None, (previous.description, line.strip())))
            annotations[-1] = replace(previous, description=description)
        else:
            summary.append(line)
            continuing = False
    return ProcedureAnnotations(
        summary='\n'.join(summary).strip() or None,
        parameters=tuple(item for item in annotations if item.tag == 'param'),
        returns=next((item for item in annotations if item.tag == 'return'), None),
    )


def referenced_aliases(proc: ProcDecl, aliases: tuple[TypeAlias, ...]) -> tuple[TypeAlias, ...]:
    by_name = {(alias.namespace, alias.name): alias for alias in aliases}
    annotations = (*proc.annotations.parameters, proc.annotations.returns)
    pending = deque(
        (proc.namespace, name)
        for item in annotations
        if item and item.type
        for name in item.type.names
    )
    result: list[TypeAlias] = []
    seen: set[tuple[str, str]] = set()
    while pending:
        namespace, name = pending.popleft()
        key = alias_key(name, namespace, by_name)
        alias = by_name.get(key) if key else None
        if alias is None or (alias.namespace, alias.name) in seen:
            continue
        seen.add((alias.namespace, alias.name))
        result.append(alias)
        pending.extend((alias.namespace, name) for name in alias.type.names)
    return tuple(result)


def parameter_label(parameter: ParameterDecl) -> str:
    return (
        f'{parameter.name}: {parameter.type_info.expression.text}'
        if parameter.type_info
        else parameter.name
    )


def return_label(proc: ProcDecl) -> str:
    return f' -> {proc.return_type.expression.text}' if proc.return_type else ''


def procedure_signature(proc: ProcDecl) -> str:
    parameters = ', '.join(parameter_label(parameter) for parameter in proc.parameters)
    return f'proc {proc.qualified_name}({parameters}){return_label(proc)}'


def procedure_documentation(proc: ProcDecl) -> str | None:
    sections = [proc.annotations.summary] if proc.annotations.summary else []
    if proc.annotations.parameters:
        sections.append(
            'Parameters:\n'
            + '\n'.join(
                f'- `{item.name}: {item.type.text}`'
                + (f': {item.description}' if item.description else '')
                for item in proc.annotations.parameters
                if item.type
            )
        )
    returns = proc.annotations.returns
    if returns and returns.type:
        sections.append(
            f'Returns: `{returns.type.text}`'
            + (f' — {returns.description}' if returns.description else '')
        )
    if proc.type_aliases:
        sections.append(
            'Types:\n'
            + '\n'.join(
                f'- `{alias.name} = {alias.type.text}`'
                + (f': {alias.description}' if alias.description else '')
                for alias in proc.type_aliases
            )
        )
    return '\n\n'.join(sections) or None
