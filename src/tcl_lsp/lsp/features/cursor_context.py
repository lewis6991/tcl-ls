from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.facts.utils import namespace_scope_id
from tcl_lsp.analysis.model import CommandCall, DocumentFacts, VariableReference
from tcl_lsp.common import offset_at_position
from tcl_lsp.lsp.state import ManagedDocument


@dataclass(frozen=True, slots=True)
class CursorContext:
    offset: int
    namespace: str
    scope_id: str | None
    attached_command_call: CommandCall | None
    command_name_prefix: str | None
    argument_index: int | None
    argument_prefix: str | None
    variable_prefix: str | None


def cursor_context(
    document: ManagedDocument,
    *,
    line: int,
    character: int,
) -> CursorContext | None:
    offset = offset_at_position(document.text, line, character)
    if offset is None:
        return None

    attached_call = _attached_command_call(
        document.text,
        document.facts.command_calls,
        offset,
    )
    active_variable_reference = _active_variable_reference(
        document.facts.variable_references,
        offset,
    )
    current_argument_context = argument_context(document.text, attached_call, offset)
    argument_prefix: str | None = None
    argument_index: int | None = None
    if current_argument_context is not None:
        argument_prefix, argument_index = current_argument_context

    namespace = (
        attached_call.namespace
        if attached_call is not None
        else namespace_at_position(document.facts, line=line, character=character)
    )
    scope_id = (
        attached_call.scope_id
        if attached_call is not None
        else active_variable_reference.scope_id
        if active_variable_reference is not None
        else None
    )
    return CursorContext(
        offset=offset,
        namespace=namespace,
        scope_id=scope_id,
        attached_command_call=attached_call,
        command_name_prefix=command_name_prefix(document.text, attached_call, offset),
        argument_index=argument_index,
        argument_prefix=argument_prefix,
        variable_prefix=_variable_prefix(
            document.text,
            active_variable_reference,
            offset,
        ),
    )


def namespace_at_position(facts: DocumentFacts, *, line: int, character: int) -> str:
    matches = [
        namespace
        for namespace in facts.namespaces
        if namespace.span.contains(line=line, character=character)
    ]
    if not matches:
        return '::'
    return min(
        matches,
        key=lambda namespace: namespace.span.end.offset - namespace.span.start.offset,
    ).qualified_name


def scope_id_at_position(facts: DocumentFacts, *, line: int, character: int) -> str:
    matching_procedures = [
        (procedure, procedure.body_span)
        for procedure in facts.procedures
        if procedure.body_span is not None and procedure.body_span.contains(line, character)
    ]
    if matching_procedures:
        procedure, _ = min(
            matching_procedures,
            key=lambda item: item[1].end.offset - item[1].start.offset,
        )
        return procedure.symbol_id
    return namespace_scope_id(namespace_at_position(facts, line=line, character=character))


def is_empty_command_position(text: str, *, offset: int) -> bool:
    index = offset - 1
    while index >= 0 and text[index] in {' ', '\t'}:
        index -= 1
    if index < 0:
        return True
    return text[index] in {'\n', ';', '['}


def _variable_prefix(
    text: str,
    active_variable_reference: VariableReference | None,
    offset: int,
) -> str | None:
    prefix_text = text[:offset]
    if prefix_text.endswith('${') or prefix_text.endswith('$'):
        return ''

    if active_variable_reference is not None:
        variable_text = text[active_variable_reference.span.start.offset : offset]
        if variable_text.startswith('${'):
            return variable_text[2:]
        if variable_text.startswith('$'):
            return variable_text[1:]

    open_brace_index = prefix_text.rfind('${')
    if open_brace_index >= 0 and '}' not in prefix_text[open_brace_index + 2 :]:
        return prefix_text[open_brace_index + 2 :]

    return None


def _active_variable_reference(
    variable_references: tuple[VariableReference, ...],
    offset: int,
) -> VariableReference | None:
    for variable_reference in reversed(variable_references):
        if variable_reference.span.start.offset < offset <= variable_reference.span.end.offset:
            return variable_reference
    return None


def _attached_command_call(
    text: str,
    command_calls: tuple[CommandCall, ...],
    offset: int,
) -> CommandCall | None:
    for command_call in reversed(command_calls):
        if _synthetic_subcommand_name_in_progress(command_call, offset):
            continue
        if command_call.span.start.offset <= offset <= command_call.span.end.offset:
            return command_call
        tail_text = text[command_call.span.end.offset : offset]
        if command_call.span.end.offset <= offset and _horizontal_whitespace_only(tail_text):
            return command_call
    return None


def _synthetic_subcommand_name_in_progress(command_call: CommandCall, offset: int) -> bool:
    return (
        command_call.name_span.start.offset > command_call.span.start.offset
        and offset <= command_call.name_span.end.offset
    )


def command_name_prefix(
    text: str,
    attached_call: CommandCall | None,
    offset: int,
) -> str | None:
    if attached_call is None:
        return None
    if attached_call.name_span.start.offset != attached_call.span.start.offset:
        return None
    if not attached_call.name_span.start.offset <= offset <= attached_call.name_span.end.offset:
        return None
    return text[attached_call.name_span.start.offset : offset]


def argument_context(
    text: str,
    attached_call: CommandCall | None,
    offset: int,
) -> tuple[str, int] | None:
    if attached_call is None:
        return None
    if attached_call.name_span.start.offset <= offset <= attached_call.name_span.end.offset:
        return None

    previous_end = attached_call.name_span.end.offset
    for index, arg_span in enumerate(attached_call.arg_spans):
        if arg_span.start.offset <= offset <= arg_span.end.offset:
            return (text[arg_span.start.offset : offset], index)
        if offset < arg_span.start.offset and _horizontal_whitespace_only(
            text[previous_end:offset]
        ):
            return ('', index)
        previous_end = arg_span.end.offset

    if not attached_call.arg_spans:
        if _horizontal_whitespace_only(text[attached_call.name_span.end.offset : offset]):
            return ('', 0)
        return None

    if attached_call.span.end.offset <= offset and _horizontal_whitespace_only(
        text[attached_call.span.end.offset : offset]
    ):
        return ('', len(attached_call.arg_spans))
    return None


def _horizontal_whitespace_only(text: str) -> bool:
    return all(char in {' ', '\t'} for char in text)
