from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.common import Span
from tcl_lsp.lsp.features.symbols import symbol_ids_at_position, symbol_kind
from tcl_lsp.lsp.state import ManagedDocument, RenameEdit


@dataclass(frozen=True, slots=True)
class PreparedRename:
    span: Span
    placeholder: str


def rename(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
    new_name: str,
) -> dict[str, tuple[RenameEdit, ...]] | None:
    if not is_valid_rename_name(new_name):
        return None

    symbol_id = rename_symbol_id_at_position(
        documents_by_uri,
        uri=uri,
        line=line,
        character=character,
    )
    if symbol_id is None:
        return None

    target_kind = symbol_kind(documents_by_uri.values(), symbol_id)
    if target_kind is None:
        return None

    edits_by_uri: dict[str, dict[tuple[int, int], RenameEdit]] = {}
    for document in documents_by_uri.values():
        if target_kind == 'function':
            for procedure in document.facts.procedures:
                if procedure.symbol_id != symbol_id:
                    continue
                add_rename_edit(
                    edits_by_uri,
                    uri=document.uri,
                    span=procedure.name_span,
                    new_text=rename_command_text(
                        document.text[
                            procedure.name_span.start.offset : procedure.name_span.end.offset
                        ],
                        new_name,
                    ),
                )
        else:
            for binding in document.facts.variable_bindings:
                if binding.symbol_id != symbol_id:
                    continue
                add_rename_edit(
                    edits_by_uri,
                    uri=document.uri,
                    span=binding.span,
                    new_text=rename_variable_text(
                        document.text[binding.span.start.offset : binding.span.end.offset],
                        new_name,
                    ),
                )

        for resolved_reference in document.analysis.resolved_references:
            if resolved_reference.symbol_id != symbol_id:
                continue
            if target_kind == 'function' and resolved_reference.reference.kind != 'command':
                continue
            if target_kind == 'variable' and resolved_reference.reference.kind != 'variable':
                continue
            reference_span = resolved_reference.reference.span
            reference_text = document.text[reference_span.start.offset : reference_span.end.offset]
            replacement = (
                rename_command_text(reference_text, new_name)
                if target_kind == 'function'
                else rename_variable_text(reference_text, new_name)
            )
            add_rename_edit(
                edits_by_uri,
                uri=document.uri,
                span=reference_span,
                new_text=replacement,
            )

    if not edits_by_uri:
        return None

    return {
        uri: tuple(
            edit
            for _, edit in sorted(
                edits.items(),
                key=lambda item: (item[1].span.start.offset, item[1].span.end.offset),
            )
        )
        for uri, edits in sorted(edits_by_uri.items())
    }


def prepare_rename(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
) -> PreparedRename | None:
    symbol_id = rename_symbol_id_at_position(
        documents_by_uri,
        uri=uri,
        line=line,
        character=character,
    )
    if symbol_id is None:
        return None

    target_kind = symbol_kind(documents_by_uri.values(), symbol_id)
    if target_kind is None:
        return None

    document = documents_by_uri.get(uri)
    if document is None:
        return None

    if target_kind == 'function':
        occurrence = _command_occurrence_at_position(
            document=document,
            symbol_id=symbol_id,
            line=line,
            character=character,
        )
        if occurrence is None:
            return None
        return _prepared_command_rename(*occurrence)

    occurrence = _variable_occurrence_at_position(
        document=document,
        symbol_id=symbol_id,
        line=line,
        character=character,
    )
    if occurrence is None:
        return None
    return _prepared_variable_rename(*occurrence)


def rename_symbol_id_at_position(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    uri: str,
    line: int,
    character: int,
) -> str | None:
    symbol_ids = symbol_ids_at_position(documents_by_uri, uri=uri, line=line, character=character)
    if len(symbol_ids) != 1:
        return None

    symbol_id = symbol_ids[0]
    if symbol_id.startswith('builtin::'):
        return None
    return symbol_id


def add_rename_edit(
    edits_by_uri: dict[str, dict[tuple[int, int], RenameEdit]],
    *,
    uri: str,
    span: Span,
    new_text: str,
) -> None:
    edits_for_uri = edits_by_uri.setdefault(uri, {})
    edits_for_uri.setdefault(
        (span.start.offset, span.end.offset),
        RenameEdit(span=span, new_text=new_text),
    )


def is_valid_rename_name(new_name: str) -> bool:
    return bool(new_name) and ':' not in new_name and is_simple_name(new_name)


def rename_command_text(text: str, new_name: str) -> str:
    if text.startswith('{') and text.endswith('}'):
        return '{' + rename_command_name_body(text[1:-1], new_name) + '}'
    if text.startswith('"') and text.endswith('"'):
        return '"' + rename_command_name_body(text[1:-1], new_name) + '"'
    return rename_command_name_body(text, new_name)


def rename_command_name_body(text: str, new_name: str) -> str:
    prefix, separator, _ = text.rpartition('::')
    if separator:
        return f'{prefix}{separator}{new_name}'
    return new_name


def rename_variable_text(text: str, new_name: str) -> str:
    if text.startswith('${') and text.endswith('}'):
        return '${' + rename_variable_name_body(text[2:-1], new_name) + '}'
    if text.startswith('$'):
        return '$' + rename_variable_name_body(text[1:], new_name)
    if text.startswith('{') and text.endswith('}'):
        return '{' + rename_variable_name_body(text[1:-1], new_name) + '}'
    if text.startswith('"') and text.endswith('"'):
        return '"' + rename_variable_name_body(text[1:-1], new_name) + '"'
    return rename_variable_name_body(text, new_name)


def rename_variable_name_body(text: str, new_name: str) -> str:
    suffix = ''
    open_paren = text.find('(')
    if open_paren > 0 and text.endswith(')'):
        suffix = text[open_paren:]
        text = text[:open_paren]

    prefix, separator, _ = text.rpartition('::')
    if separator:
        return f'{prefix}{separator}{new_name}{suffix}'
    return new_name + suffix


def _command_occurrence_at_position(
    *,
    document: ManagedDocument,
    symbol_id: str,
    line: int,
    character: int,
) -> tuple[Span, str] | None:
    for procedure in document.facts.procedures:
        if procedure.symbol_id != symbol_id or not procedure.name_span.contains(line, character):
            continue
        return (
            procedure.name_span,
            document.text[procedure.name_span.start.offset : procedure.name_span.end.offset],
        )

    for resolved_reference in document.analysis.resolved_references:
        if (
            resolved_reference.symbol_id != symbol_id
            or resolved_reference.reference.kind != 'command'
        ):
            continue
        span = resolved_reference.reference.span
        if not span.contains(line, character):
            continue
        return (span, document.text[span.start.offset : span.end.offset])

    return None


def _variable_occurrence_at_position(
    *,
    document: ManagedDocument,
    symbol_id: str,
    line: int,
    character: int,
) -> tuple[Span, str] | None:
    for binding in document.facts.variable_bindings:
        if binding.symbol_id != symbol_id or not binding.span.contains(line, character):
            continue
        return (
            binding.span,
            document.text[binding.span.start.offset : binding.span.end.offset],
        )

    for resolved_reference in document.analysis.resolved_references:
        if (
            resolved_reference.symbol_id != symbol_id
            or resolved_reference.reference.kind != 'variable'
        ):
            continue
        span = resolved_reference.reference.span
        if not span.contains(line, character):
            continue
        return (span, document.text[span.start.offset : span.end.offset])

    return None


def _prepared_command_rename(span: Span, text: str) -> PreparedRename | None:
    prefix_length = 0
    content = text
    if text.startswith('{') and text.endswith('}'):
        prefix_length = 1
        content = text[1:-1]
    elif text.startswith('"') and text.endswith('"'):
        prefix_length = 1
        content = text[1:-1]

    _, _, tail = content.rpartition('::')
    if not tail:
        return None

    tail_start = len(content) - len(tail)
    return PreparedRename(
        span=_subspan(span, text, prefix_length + tail_start, prefix_length + len(content)),
        placeholder=tail,
    )


def _prepared_variable_rename(span: Span, text: str) -> PreparedRename | None:
    prefix_length = 0
    content = text
    if text.startswith('${') and text.endswith('}'):
        prefix_length = 2
        content = text[2:-1]
    elif text.startswith('$'):
        prefix_length = 1
        content = text[1:]
    elif text.startswith('{') and text.endswith('}'):
        prefix_length = 1
        content = text[1:-1]
    elif text.startswith('"') and text.endswith('"'):
        prefix_length = 1
        content = text[1:-1]

    name_body = content
    open_paren = content.find('(')
    if open_paren > 0 and content.endswith(')'):
        name_body = content[:open_paren]

    _, _, tail = name_body.rpartition('::')
    if not tail:
        return None

    tail_start = len(name_body) - len(tail)
    return PreparedRename(
        span=_subspan(span, text, prefix_length + tail_start, prefix_length + len(name_body)),
        placeholder=tail,
    )


def _subspan(span: Span, text: str, start_index: int, end_index: int) -> Span:
    if start_index == 0 and end_index == len(text):
        return span

    return Span(
        start=span.start.advance(text[:start_index]),
        end=span.start.advance(text[:end_index]),
    )
