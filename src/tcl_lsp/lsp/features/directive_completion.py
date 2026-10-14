from __future__ import annotations

import re

from lsprotocol import types

from tcl_lsp.analysis.metadata_commands import metadata_module_names
from tcl_lsp.common import offset_at_position
from tcl_lsp.diagnostic_catalog import DIAGNOSTIC_DESCRIPTIONS
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry

_LEVEL_DESCRIPTIONS = {
    'error': 'Report as an error.',
    'warning': 'Report as a warning.',
    'information': 'Report as information.',
    'hint': 'Report as a hint.',
    'off': 'Disable matching diagnostics.',
    'default': 'Restore the built-in severity, including after an earlier suppression.',
}


def directive_completion_items(
    document: ManagedDocument,
    *,
    metadata_registry: MetadataRegistry,
    line: int,
    character: int,
) -> tuple[types.CompletionItem, ...] | None:
    if not document.facts.directive_comments:
        return None
    offset = offset_at_position(document.text, line, character)
    if offset is None:
        return None
    comment = next(
        (
            span
            for span in document.facts.directive_comments
            if span.start.offset < offset <= span.end.offset
        ),
        None,
    )
    if comment is None:
        return None

    before = document.text[comment.start.offset + 1 : offset]
    if '\n' in before:
        return ()
    matches = list(re.finditer(r'\S+', before))
    if matches and not before[-1].isspace():
        prefix = matches[-1].group()
        completed = [match.group() for match in matches[:-1]]
    else:
        prefix = ''
        completed = [match.group() for match in matches]

    choices, kind = _choices(completed, metadata_registry)
    # Replace the whole word when completing in its middle. This also keeps
    # hyphenated codes and directives intact across client word-boundary rules.
    end = offset
    while end < comment.end.offset and not document.text[end].isspace():
        end += 1
    edit_range = types.Range(
        start=types.Position(line=line, character=character - len(prefix)),
        end=types.Position(line=line, character=character + end - offset),
    )
    return tuple(
        types.CompletionItem(
            label=label,
            kind=kind,
            documentation=types.MarkupContent(kind=types.MarkupKind.PlainText, value=description),
            text_edit=types.TextEdit(range=edit_range, new_text=label),
        )
        for label, description in sorted(choices.items())
        if label.startswith(prefix)
    )


def _choices(
    completed: list[str], metadata_registry: MetadataRegistry
) -> tuple[dict[str, str], types.CompletionItemKind]:
    keyword = types.CompletionItemKind.Keyword
    value = types.CompletionItemKind.EnumMember
    if not completed:
        return {'tcl-ls:': 'Language-server source directive.'}, keyword
    if completed == ['tcl-ls:']:
        return {
            'diagnostic': 'diagnostic code level\nApply to the next Tcl command, including its bodies and command substitutions.',
            'diagnostic-file': 'diagnostic-file code level\nApply to the whole file, including code before the comment.',
            'module': 'module name\nSelect a metadata module for this Tcl body.',
        }, keyword
    if completed[:2] == ['tcl-ls:', 'module'] and len(completed) == 2:
        return dict.fromkeys(
            metadata_module_names(metadata_registry.catalog), 'Select this metadata module.'
        ), types.CompletionItemKind.Module
    if completed[0] != 'tcl-ls:' or completed[1] not in {'diagnostic', 'diagnostic-file'}:
        return {}, keyword

    match len(completed):
        case 2:
            return {'*': 'All diagnostic codes.', **DIAGNOSTIC_DESCRIPTIONS}, value
        case 3:
            return _LEVEL_DESCRIPTIONS, value
        case _:
            return {}, keyword
