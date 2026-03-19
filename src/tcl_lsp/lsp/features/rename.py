from __future__ import annotations

from collections.abc import Mapping

from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.common import Span
from tcl_lsp.lsp.features.symbols import symbol_ids_at_position, symbol_kind
from tcl_lsp.lsp.state import ManagedDocument, RenameEdit


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
