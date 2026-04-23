from __future__ import annotations

from functools import cache
from typing import Literal

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.metadata_commands import (
    parse_selector_tokens,
    validate_context_body_selector,
    validate_context_owner_selector,
    validate_procedure_selector,
)
from tcl_lsp.analysis.model import BINDING_KINDS
from tcl_lsp.common import Position

type StructuredMatchState = Literal['unstructured', 'exact', 'dynamic', 'reject']

_ZERO_POSITION = Position(offset=0, line=0, character=0)
_SLOT_DISPLAY_NAMES = {
    'groupedShape': 'shape',
}


def display_metadata_signature(signature: str) -> str:
    items = _signature_items(signature)
    if not items or not any(
        _is_literal_token(item) or _slot_name(item) is not None for item in items
    ):
        return signature.strip()
    return ' '.join(_display_token(item) for item in items)


def is_structured_metadata_signature(signature: str) -> bool:
    return any(
        _is_literal_token(item) or _slot_name(item) is not None
        for item in _signature_items(signature)
    )


def metadata_signature_match_state(
    signature: str,
    *,
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...],
    arg_grouped: tuple[bool, ...],
) -> StructuredMatchState:
    items = _signature_items(signature)
    if not any(_is_literal_token(item) or _slot_name(item) is not None for item in items):
        return 'unstructured'
    return _match_signature_items(
        items,
        arg_texts=arg_texts,
        arg_expanded=arg_expanded,
        arg_grouped=arg_grouped,
        item_index=0,
        arg_index=0,
    )


@cache
def _signature_items(signature: str) -> tuple[str, ...]:
    text = signature.strip()
    if not text or text == '{}':
        return ()
    items = tuple(item.text for item in split_tcl_list(text, _ZERO_POSITION))
    if not items or items == ('',):
        return ()
    return items


def _display_token(token: str) -> str:
    if _is_literal_token(token):
        return token[1:]
    slot_name = _slot_name(token)
    if slot_name is not None:
        return _SLOT_DISPLAY_NAMES.get(slot_name, slot_name)
    return token


def _match_signature_items(
    items: tuple[str, ...],
    *,
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...],
    arg_grouped: tuple[bool, ...],
    item_index: int,
    arg_index: int,
) -> StructuredMatchState:
    if item_index >= len(items):
        return 'exact' if arg_index == len(arg_texts) else 'reject'

    token = items[item_index]
    if token == 'args':
        return 'exact'

    if arg_index >= len(arg_texts):
        return 'reject'

    if _is_literal_token(token):
        return _combine_match_states(
            _match_literal_token(
                token,
                arg_texts=arg_texts,
                arg_expanded=arg_expanded,
                arg_index=arg_index,
            ),
            _match_signature_items(
                items,
                arg_texts=arg_texts,
                arg_expanded=arg_expanded,
                arg_grouped=arg_grouped,
                item_index=item_index + 1,
                arg_index=arg_index + 1,
            ),
        )

    slot_name = _slot_name(token)
    if slot_name is None:
        return _match_signature_items(
            items,
            arg_texts=arg_texts,
            arg_expanded=arg_expanded,
            arg_grouped=arg_grouped,
            item_index=item_index + 1,
            arg_index=arg_index + 1,
        )

    if slot_name not in {'selector', 'bodySelector', 'ownerSelector', 'procedureSelector'}:
        return _combine_match_states(
            _match_slot_token(
                slot_name,
                arg_texts=arg_texts,
                arg_expanded=arg_expanded,
                arg_grouped=arg_grouped,
                arg_index=arg_index,
            ),
            _match_signature_items(
                items,
                arg_texts=arg_texts,
                arg_expanded=arg_expanded,
                arg_grouped=arg_grouped,
                item_index=item_index + 1,
                arg_index=arg_index + 1,
            ),
        )

    best_state: StructuredMatchState = 'reject'
    for next_index in range(arg_index + 1, len(arg_texts) + 1):
        selector_state = _match_selector_slot(
            slot_name=slot_name,
            arg_texts=arg_texts,
            arg_expanded=arg_expanded,
            arg_index=arg_index,
            next_index=next_index,
        )
        if selector_state == 'reject':
            continue
        best_state = _best_match_state(
            best_state,
            _combine_match_states(
                selector_state,
                _match_signature_items(
                    items,
                    arg_texts=arg_texts,
                    arg_expanded=arg_expanded,
                    arg_grouped=arg_grouped,
                    item_index=item_index + 1,
                    arg_index=next_index,
                ),
            ),
        )
        if best_state == 'exact':
            return best_state
    return best_state


def _match_literal_token(
    token: str,
    *,
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...],
    arg_index: int,
) -> StructuredMatchState:
    actual = arg_texts[arg_index]
    if actual is None or arg_expanded[arg_index]:
        return 'dynamic'
    return 'exact' if actual == token[1:] else 'reject'


def _match_slot_token(
    slot_name: str,
    *,
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...],
    arg_grouped: tuple[bool, ...],
    arg_index: int,
) -> StructuredMatchState:
    actual = arg_texts[arg_index]
    if actual is None or arg_expanded[arg_index]:
        return 'dynamic'

    if slot_name in {'name', 'procName'}:
        return 'exact' if ' ' not in actual else 'reject'
    if slot_name == 'shape':
        return 'exact'
    if slot_name == 'groupedShape':
        return 'exact' if arg_grouped[arg_index] else 'reject'
    if slot_name == 'language':
        return 'exact' if ' ' not in actual else 'reject'
    if slot_name == 'kind':
        return 'exact' if actual in BINDING_KINDS else 'reject'
    if slot_name in {
        'body',
        'commandPrefix',
        'packageName',
        'script',
        'value',
    }:
        return 'exact'
    return 'reject'


def _match_selector_slot(
    *,
    slot_name: str,
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...],
    arg_index: int,
    next_index: int,
) -> StructuredMatchState:
    selector_words = arg_texts[arg_index:next_index]
    selector_expanded = arg_expanded[arg_index:next_index]
    if any(text is None for text in selector_words) or any(selector_expanded):
        return 'dynamic'

    try:
        selector, consumed = parse_selector_tokens(
            tuple(text for text in selector_words if text is not None),
            command_name='signature',
        )
        if slot_name == 'bodySelector':
            validate_context_body_selector(selector, command_name='signature')
        elif slot_name == 'ownerSelector':
            validate_context_owner_selector(selector, command_name='signature')
        elif slot_name == 'procedureSelector':
            validate_procedure_selector(selector, command_name='signature', role='selector')
    except RuntimeError:
        return 'reject'
    return 'exact' if consumed == len(selector_words) else 'reject'


def _combine_match_states(
    left: StructuredMatchState,
    right: StructuredMatchState,
) -> StructuredMatchState:
    if left == 'reject' or right == 'reject':
        return 'reject'
    if left == 'dynamic' or right == 'dynamic':
        return 'dynamic'
    if left == 'unstructured':
        return right
    if right == 'unstructured':
        return left
    return 'exact'


def _best_match_state(
    current: StructuredMatchState,
    candidate: StructuredMatchState,
) -> StructuredMatchState:
    ordering = {
        'reject': 0,
        'unstructured': 1,
        'dynamic': 2,
        'exact': 3,
    }
    return candidate if ordering[candidate] > ordering[current] else current


def _is_literal_token(token: str) -> bool:
    return token.startswith('=') and len(token) > 1


def _slot_name(token: str) -> str | None:
    if len(token) <= 2 or not token.startswith('<') or not token.endswith('>'):
        return None
    return token[1:-1]
