from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.model import (
    CommandCall,
    DocumentFacts,
    NamespaceScope,
    ParameterDecl,
    ProcDecl,
    VarBinding,
    VariableReference,
)
from tcl_lsp.common import Diagnostic, DocumentSymbol, Position, Span
from tcl_lsp.parser import Parser, collect_variable_substitutions, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    ParseResult,
    Script,
    Word,
)

_SIMPLE_NAME_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:')


@dataclass(frozen=True, slots=True)
class _ExtractionContext:
    uri: str
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None


@dataclass(frozen=True, slots=True)
class _ListItem:
    text: str
    span: Span
    content_start: Position


class FactExtractor:
    def __init__(self, parser: Parser | None = None) -> None:
        self._parser = Parser() if parser is None else parser

    def extract(self, parse_result: ParseResult) -> DocumentFacts:
        collector = _FactCollector(parser=self._parser, parse_result=parse_result)
        return collector.collect()


class _FactCollector:
    def __init__(self, parser: Parser, parse_result: ParseResult) -> None:
        self._parser = parser
        self._parse_result = parse_result
        self._diagnostics: list[Diagnostic] = list(parse_result.diagnostics)
        self._namespaces: list[NamespaceScope] = []
        self._procedures: list[ProcDecl] = []
        self._variable_bindings: list[VarBinding] = []
        self._command_calls: list[CommandCall] = []
        self._variable_references: list[VariableReference] = []

    def collect(self) -> DocumentFacts:
        root_context = _ExtractionContext(
            uri=self._parse_result.source_id,
            namespace='::',
            scope_id=_namespace_scope_id('::'),
            procedure_symbol_id=None,
        )
        self._collect_script(self._parse_result.script, root_context)
        return DocumentFacts(
            uri=self._parse_result.source_id,
            parse_result=self._parse_result,
            namespaces=tuple(self._namespaces),
            procedures=tuple(self._procedures),
            variable_bindings=tuple(self._variable_bindings),
            command_calls=tuple(self._command_calls),
            variable_references=tuple(self._variable_references),
            document_symbols=tuple(self._build_document_symbols()),
            diagnostics=tuple(self._diagnostics),
        )

    def _collect_script(self, script: Script, context: _ExtractionContext) -> None:
        for command in script.commands:
            self._collect_command(command, context)

    def _collect_command(self, command: Command, context: _ExtractionContext) -> None:
        if not command.words:
            return

        command_name_word = command.words[0]
        command_name = word_static_text(command_name_word)
        self._command_calls.append(
            CommandCall(
                uri=context.uri,
                name=command_name,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                span=command.span,
                name_span=command_name_word.span,
                dynamic=command_name is None,
            )
        )

        for word in command.words:
            self._collect_word_references(word, context)

        if command_name == 'proc':
            self._collect_proc(command, context)
            return

        if command_name == 'namespace':
            self._collect_namespace_eval(command, context)
            return

        if command_name == 'set':
            self._collect_set(command, context)
            return

        if command_name == 'foreach':
            self._collect_foreach(command, context)

    def _collect_word_references(self, word: Word, context: _ExtractionContext) -> None:
        for substitution in collect_variable_substitutions(word):
            self._variable_references.append(
                VariableReference(
                    uri=context.uri,
                    name=substitution.name,
                    namespace=context.namespace,
                    scope_id=context.scope_id,
                    procedure_symbol_id=context.procedure_symbol_id,
                    span=substitution.span,
                )
            )

        if isinstance(word, BracedWord):
            return

        for part in word.parts:
            if isinstance(part, CommandSubstitution):
                self._collect_script(part.script, context)

    def _collect_proc(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 4:
            return

        name_word = command.words[1]
        args_word = command.words[2]
        body_word = command.words[3]
        raw_name = word_static_text(name_word)
        if raw_name is None:
            return

        qualified_name = _qualify_name(raw_name, context.namespace)
        proc_symbol_id = _proc_symbol_id(context.uri, qualified_name, name_word.span.start.offset)
        parameter_items = self._parse_parameter_items(args_word)
        parameters: list[ParameterDecl] = []
        for item in parameter_items:
            parameter_name, parameter_span = self._parameter_from_item(item)
            if parameter_name is None:
                continue
            parameters.append(
                ParameterDecl(
                    symbol_id=_variable_symbol_id(context.uri, proc_symbol_id, parameter_name),
                    name=parameter_name,
                    span=parameter_span,
                )
            )

        proc_decl = ProcDecl(
            symbol_id=proc_symbol_id,
            uri=context.uri,
            name=raw_name,
            qualified_name=qualified_name,
            namespace=_namespace_for_name(qualified_name),
            span=command.span,
            name_span=name_word.span,
            parameters=tuple(parameters),
            body_span=_body_span(body_word),
        )
        self._procedures.append(proc_decl)

        for parameter in parameters:
            self._variable_bindings.append(
                VarBinding(
                    symbol_id=parameter.symbol_id,
                    uri=context.uri,
                    name=parameter.name,
                    scope_id=proc_symbol_id,
                    namespace=proc_decl.namespace,
                    procedure_symbol_id=proc_symbol_id,
                    kind='parameter',
                    span=parameter.span,
                )
            )

        embedded_body = _extract_static_script(body_word)
        if embedded_body is None:
            return

        body_result = self._parser.parse_embedded_script(
            source_id=context.uri,
            text=embedded_body[0],
            start_position=embedded_body[1],
        )
        self._diagnostics.extend(body_result.diagnostics)
        body_context = _ExtractionContext(
            uri=context.uri,
            namespace=proc_decl.namespace,
            scope_id=proc_symbol_id,
            procedure_symbol_id=proc_symbol_id,
        )
        self._collect_script(body_result.script, body_context)

    def _collect_namespace_eval(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 4:
            return
        eval_keyword = word_static_text(command.words[1])
        namespace_name = word_static_text(command.words[2])
        if eval_keyword != 'eval' or namespace_name is None:
            return

        qualified_namespace = _qualify_namespace(namespace_name, context.namespace)
        namespace_scope = NamespaceScope(
            uri=context.uri,
            name=namespace_name,
            qualified_name=qualified_namespace,
            span=command.words[2].span,
            selection_span=command.words[2].span,
        )
        self._namespaces.append(namespace_scope)

        if context.procedure_symbol_id is not None:
            return

        body_word = command.words[3]
        embedded_body = _extract_static_script(body_word)
        if embedded_body is None:
            return

        body_result = self._parser.parse_embedded_script(
            source_id=context.uri,
            text=embedded_body[0],
            start_position=embedded_body[1],
        )
        self._diagnostics.extend(body_result.diagnostics)
        self._collect_script(
            body_result.script,
            _ExtractionContext(
                uri=context.uri,
                namespace=qualified_namespace,
                scope_id=_namespace_scope_id(qualified_namespace),
                procedure_symbol_id=None,
            ),
        )

    def _collect_set(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 2:
            return
        variable_name = word_static_text(command.words[1])
        if variable_name is None or not _is_simple_name(variable_name):
            return

        if len(command.words) >= 3:
            self._variable_bindings.append(
                VarBinding(
                    symbol_id=_variable_symbol_id(context.uri, context.scope_id, variable_name),
                    uri=context.uri,
                    name=variable_name,
                    scope_id=context.scope_id,
                    namespace=context.namespace,
                    procedure_symbol_id=context.procedure_symbol_id,
                    kind='set',
                    span=command.words[1].span,
                )
            )
            return

        self._variable_references.append(
            VariableReference(
                uri=context.uri,
                name=variable_name,
                namespace=context.namespace,
                scope_id=context.scope_id,
                procedure_symbol_id=context.procedure_symbol_id,
                span=command.words[1].span,
            )
        )

    def _collect_foreach(self, command: Command, context: _ExtractionContext) -> None:
        if len(command.words) < 4:
            return
        variables = self._parse_list_items(command.words[1])
        for item in variables:
            if not _is_simple_name(item.text):
                continue
            self._variable_bindings.append(
                VarBinding(
                    symbol_id=_variable_symbol_id(context.uri, context.scope_id, item.text),
                    uri=context.uri,
                    name=item.text,
                    scope_id=context.scope_id,
                    namespace=context.namespace,
                    procedure_symbol_id=context.procedure_symbol_id,
                    kind='foreach',
                    span=item.span,
                )
            )

        embedded_body = _extract_static_script(command.words[3])
        if embedded_body is None:
            return

        body_result = self._parser.parse_embedded_script(
            source_id=context.uri,
            text=embedded_body[0],
            start_position=embedded_body[1],
        )
        self._diagnostics.extend(body_result.diagnostics)
        self._collect_script(body_result.script, context)

    def _parse_parameter_items(self, word: Word) -> tuple[_ListItem, ...]:
        return tuple(self._parse_list_items(word))

    def _parse_list_items(self, word: Word) -> list[_ListItem]:
        static_text = word_static_text(word)
        if static_text is None:
            return []
        return _split_tcl_list(static_text, _body_start(word))

    def _parameter_from_item(self, item: _ListItem) -> tuple[str | None, Span]:
        if ' ' not in item.text and '\t' not in item.text and '\n' not in item.text:
            return item.text, item.span

        subitems = _split_tcl_list(item.text, item.content_start)
        if not subitems:
            return None, item.span
        return subitems[0].text, subitems[0].span

    def _build_document_symbols(self) -> list[DocumentSymbol]:
        symbols: list[DocumentSymbol] = []
        for namespace in sorted(self._namespaces, key=lambda item: item.span.start.offset):
            symbols.append(
                DocumentSymbol(
                    name=namespace.qualified_name,
                    kind='namespace',
                    span=namespace.span,
                    selection_span=namespace.selection_span,
                    children=(),
                )
            )
        for proc in sorted(self._procedures, key=lambda item: item.name_span.start.offset):
            symbols.append(
                DocumentSymbol(
                    name=proc.qualified_name,
                    kind='function',
                    span=proc.span,
                    selection_span=proc.name_span,
                    children=(),
                )
            )
        return symbols


def _extract_static_script(word: Word) -> tuple[str, Position] | None:
    text = word_static_text(word)
    if text is None:
        return None
    return text, _body_start(word)


def _body_start(word: Word) -> Position:
    return word.content_span.start


def _body_span(word: Word) -> Span:
    return word.content_span


def _split_tcl_list(text: str, start_position: Position) -> list[_ListItem]:
    items: list[_ListItem] = []
    index = 0
    position = start_position

    while index < len(text):
        while index < len(text) and text[index].isspace():
            position = position.advance(text[index])
            index += 1
        if index >= len(text):
            break

        item_start_position = position
        current_char = text[index]
        if current_char == '{':
            raw_text, consumed, position, content_start = _consume_braced_item(
                text[index:], position
            )
            index += consumed
            items.append(
                _ListItem(
                    text=raw_text,
                    span=Span(start=item_start_position, end=position),
                    content_start=content_start,
                )
            )
            continue
        if current_char == '"':
            raw_text, consumed, position, content_start = _consume_quoted_item(
                text[index:], position
            )
            index += consumed
            items.append(
                _ListItem(
                    text=raw_text,
                    span=Span(start=item_start_position, end=position),
                    content_start=content_start,
                )
            )
            continue

        item_text, consumed, position = _consume_plain_item(text[index:], position)
        index += consumed
        items.append(
            _ListItem(
                text=item_text,
                span=Span(start=item_start_position, end=position),
                content_start=item_start_position,
            )
        )

    return items


def _consume_braced_item(
    text: str, start_position: Position
) -> tuple[str, int, Position, Position]:
    index = 0
    position = start_position
    position = position.advance(text[index])
    index += 1
    content_start = position
    depth = 1
    parts: list[str] = []

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            if index < len(text):
                parts.append(text[index])
                position = position.advance(text[index])
                index += 1
            continue
        if current_char == '{':
            depth += 1
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            continue
        if current_char == '}':
            depth -= 1
            if depth == 0:
                position = position.advance(current_char)
                index += 1
                return ''.join(parts), index, position, content_start
            parts.append(current_char)
            position = position.advance(current_char)
            index += 1
            continue
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1

    return ''.join(parts), index, position, content_start


def _consume_quoted_item(
    text: str, start_position: Position
) -> tuple[str, int, Position, Position]:
    index = 0
    position = start_position
    position = position.advance(text[index])
    index += 1
    content_start = position
    parts: list[str] = []

    while index < len(text):
        current_char = text[index]
        if current_char == '"':
            position = position.advance(current_char)
            index += 1
            return ''.join(parts), index, position, content_start
        if current_char == '\\' and index + 1 < len(text):
            index += 1
            current_char = text[index]
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1

    return ''.join(parts), index, position, content_start


def _consume_plain_item(text: str, start_position: Position) -> tuple[str, int, Position]:
    index = 0
    position = start_position
    parts: list[str] = []
    while index < len(text) and not text[index].isspace():
        current_char = text[index]
        if current_char == '\\' and index + 1 < len(text):
            index += 1
            current_char = text[index]
        parts.append(current_char)
        position = position.advance(current_char)
        index += 1
    return ''.join(parts), index, position


def _qualify_name(name: str, current_namespace: str) -> str:
    if name.startswith('::'):
        return _normalize_qualified_name(name)
    if current_namespace == '::':
        return f'::{name}'
    return f'{current_namespace}::{name}'


def _qualify_namespace(name: str, current_namespace: str) -> str:
    if name == '::':
        return '::'
    return _qualify_name(name, current_namespace)


def _normalize_qualified_name(name: str) -> str:
    segments = [segment for segment in name.split('::') if segment]
    if not segments:
        return '::'
    return '::' + '::'.join(segments)


def _namespace_for_name(qualified_name: str) -> str:
    segments = [segment for segment in qualified_name.split('::') if segment]
    if len(segments) <= 1:
        return '::'
    return '::' + '::'.join(segments[:-1])


def _namespace_scope_id(namespace: str) -> str:
    return f'namespace::{namespace}'


def _proc_symbol_id(uri: str, qualified_name: str, offset: int) -> str:
    return f'proc::{uri}::{qualified_name}::{offset}'


def _variable_symbol_id(uri: str, scope_id: str, name: str) -> str:
    return f'var::{uri}::{scope_id}::{name}'


def _is_simple_name(name: str) -> bool:
    return bool(name) and all(char in _SIMPLE_NAME_CHARS for char in name)
