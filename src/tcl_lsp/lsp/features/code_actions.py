from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase

from lsprotocol import types
from pygls.workspace.position_codec import PositionCodec, ServerTextRange

from tcl_lsp.common import Diagnostic, Position, Span, lsp_position
from tcl_lsp.lsp.diagnostics import lsp_diagnostic
from tcl_lsp.lsp.state import ManagedDocument


def diagnostic_code_actions(
    document: ManagedDocument,
    request_range: types.Range,
    *,
    position_codec: PositionCodec,
    only: Sequence[types.CodeActionKind | str] | None = None,
    versioned_edits: bool = False,
) -> list[types.CodeAction]:
    if only is not None and not any(
        not kind or kind == types.CodeActionKind.QuickFix for kind in only
    ):
        return []

    actions: dict[tuple[str, str, int], types.CodeAction] = {}
    newline = '\r\n' if '\r\n' in document.text else '\n'
    file_position = _file_comment_position(document, newline)
    source_range = position_codec.range_from_client_units(
        document.text.splitlines(keepends=True), request_range
    )

    # Client diagnostics can be stale or belong to another server. Use the
    # current analysis and the requested range instead.
    for diagnostic in document.analysis.diagnostics:
        if not _overlaps(diagnostic.span, source_range):
            continue

        command = _command_span(document, diagnostic)
        if command is not None:
            position = command.start
            line_start = position.offset - position.character
            indentation = document.text[line_start : position.offset]
            _add_action(
                actions,
                document,
                diagnostic,
                scope='command',
                position=Position(line_start, position.line, 0),
                before=indentation,
                after=newline,
                versioned_edits=versioned_edits,
                position_codec=position_codec,
            )

        # Command rules take precedence over all file rules. A new file
        # comment cannot suppress a diagnostic with a command override.
        if not _has_command_override(document, diagnostic):
            position, before, after = file_position
            _add_action(
                actions,
                document,
                diagnostic,
                scope='file',
                position=position,
                before=before,
                after=after,
                versioned_edits=versioned_edits,
                position_codec=position_codec,
            )

    return list(actions.values())


def _overlaps(span: Span, request_range: ServerTextRange) -> bool:
    start = (request_range.start.line, request_range.start.character)
    end = (request_range.end.line, request_range.end.character)
    span_start = (span.start.line, span.start.character)
    span_end = (span.end.line, span.end.character)
    if start == end:
        return span_start <= start < span_end or span_start == span_end == start
    if span_start == span_end:
        return start <= span_start < end
    return span_start < end and start < span_end


def _command_span(document: ManagedDocument, diagnostic: Diagnostic) -> Span | None:
    candidates = sorted(
        {
            call.span
            for call in document.facts.command_calls
            if call.span.start.offset <= diagnostic.span.start.offset < call.span.end.offset
        },
        key=lambda span: span.end.offset - span.start.offset,
    )
    for span in candidates:
        prefix = document.text[span.start.offset - span.start.character : span.start.offset]
        if prefix.strip(' \t'):
            continue
        if _has_command_override(document, diagnostic, after=span.start.offset):
            continue
        return span
    return None


def _has_command_override(
    document: ManagedDocument, diagnostic: Diagnostic, *, after: int = -1
) -> bool:
    return any(
        rule.command is not None
        and rule.command.start.offset > after
        and rule.command.start.offset <= diagnostic.span.start.offset < rule.command.end.offset
        and fnmatchcase(diagnostic.code, rule.code)
        for rule in document.facts.diagnostic_rules
    )


def _file_comment_position(document: ManagedDocument, newline: str) -> tuple[Position, str, str]:
    # Place the new rule after existing file rules, which use source order.
    for rule in reversed(document.facts.diagnostic_rules):
        span = rule.directive_span
        if rule.command is not None or span is None:
            continue
        prefix = document.text[span.start.offset - span.start.character : span.start.offset]
        indentation = prefix if not prefix.strip(' \t') else ''
        if document.text[span.end.offset : span.end.offset + 1] == '\n':
            return Position(span.end.offset + 1, span.end.line + 1, 0), indentation, newline
        return span.end, newline + indentation, ''

    # Preserve an executable script's interpreter line.
    if document.text.startswith('#!'):
        end = document.text.find('\n')
        if end >= 0:
            return Position(end + 1, 1, 0), '', newline
        return Position(len(document.text), 0, len(document.text)), newline, newline
    return Position(0, 0, 0), '', newline


def _add_action(
    actions: dict[tuple[str, str, int], types.CodeAction],
    document: ManagedDocument,
    diagnostic: Diagnostic,
    *,
    scope: str,
    position: Position,
    before: str,
    after: str,
    versioned_edits: bool,
    position_codec: PositionCodec,
) -> None:
    key = (scope, diagnostic.code, position.offset)
    existing = actions.get(key)
    if existing is not None:
        assert isinstance(existing.diagnostics, list)
        existing.diagnostics.append(lsp_diagnostic(diagnostic))
        return

    insertion = lsp_position(position)
    if position.character:
        prefix = document.text[position.offset - position.character : position.offset]
        insertion.character = position_codec.client_num_units(prefix)
    directive = 'diagnostic-file' if scope == 'file' else 'diagnostic'
    edit = types.TextEdit(
        range=types.Range(start=insertion, end=insertion),
        new_text=f'{before}# tcl-ls: {directive} {diagnostic.code} off{after}',
    )
    workspace_edit = (
        types.WorkspaceEdit(
            document_changes=[
                types.TextDocumentEdit(
                    text_document=types.OptionalVersionedTextDocumentIdentifier(
                        uri=document.uri, version=document.version
                    ),
                    edits=[edit],
                )
            ]
        )
        if versioned_edits
        else types.WorkspaceEdit(changes={document.uri: [edit]})
    )
    actions[key] = types.CodeAction(
        title=f'Suppress {diagnostic.code} for this {scope}',
        kind=types.CodeActionKind.QuickFix,
        diagnostics=[lsp_diagnostic(diagnostic)],
        edit=workspace_edit,
    )
