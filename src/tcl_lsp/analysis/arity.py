from __future__ import annotations

from tcl_lsp.analysis.facts.parsing import ListItem, is_simple_name, split_tcl_list
from tcl_lsp.analysis.model import CommandArity
from tcl_lsp.common import Position

_ZERO_POSITION = Position(offset=0, line=0, character=0)
_DEFAULT_LITERAL_KEYWORDS = frozenset({'start'})


def proc_parameter_arity(items: tuple[ListItem, ...]) -> CommandArity | None:
    min_args = 0
    max_args = 0

    for index, item in enumerate(items):
        parameter = _proc_parameter_spec(item)
        if parameter is None:
            return None

        name, optional = parameter
        if name == 'args':
            if optional or index != len(items) - 1:
                return None
            return CommandArity(min_args=min_args, max_args=None)

        if not optional:
            min_args += 1
        max_args += 1

    return CommandArity(min_args=min_args, max_args=max_args)


def metadata_signature_arity(signature: str) -> CommandArity | None:
    text = signature.strip()
    if not text or text == '{}':
        return CommandArity(min_args=0, max_args=0)

    items = tuple(item.text for item in split_tcl_list(text, _ZERO_POSITION))
    if not items or items == ('',):
        return CommandArity(min_args=0, max_args=0)
    return _signature_items_arity(items)


def _signature_items_arity(items: tuple[str, ...]) -> CommandArity | None:
    min_args = 0
    max_args = 0
    index = 0

    while index < len(items):
        token = items[index]
        if token == '?':
            try:
                group_end = items.index('?', index + 1)
            except ValueError:
                return None

            group_arity = _optional_group_arity(items[index + 1 : group_end])
            if group_arity is None:
                return None

            max_args += group_arity.max_args
            index = group_end + 1
            continue

        token_arity = _signature_token_arity(token, is_last=index == len(items) - 1)
        if token_arity is None:
            return None

        min_args += token_arity.min_args
        if token_arity.max_args is None:
            if index != len(items) - 1:
                return None
            return CommandArity(min_args=min_args, max_args=None)

        max_args += token_arity.max_args
        index += 1

    return CommandArity(min_args=min_args, max_args=max_args)


def _optional_group_arity(tokens: tuple[str, ...]) -> CommandArity | None:
    if not tokens:
        return None

    max_args = 0
    for token in tokens:
        token_arity = _signature_token_arity(token, is_last=False)
        if token_arity is None or token_arity.max_args is None:
            return None
        max_args += token_arity.max_args
    return CommandArity(min_args=0, max_args=max_args)


def _signature_token_arity(token: str, *, is_last: bool) -> CommandArity | None:
    if not token:
        return CommandArity(min_args=0, max_args=0)
    if token == 'args':
        if not is_last:
            return None
        return CommandArity(min_args=0, max_args=None)
    if _is_safe_inline_optional_literal(token):
        return CommandArity(min_args=0, max_args=1)
    if token == '?' or '...' in token or '|' in token or '?' in token:
        return None
    if not _has_internal_whitespace(token):
        return CommandArity(min_args=1, max_args=1)

    default_arity = _default_like_token_arity(token)
    if default_arity is not None:
        return default_arity
    return None


def _proc_parameter_spec(item: ListItem) -> tuple[str, bool] | None:
    if not _has_internal_whitespace(item.text):
        return item.text, False

    subitems = split_tcl_list(item.text, item.content_start)
    if len(subitems) != 2 or not is_simple_name(subitems[0].text):
        return None
    return subitems[0].text, True


def _default_like_token_arity(token: str) -> CommandArity | None:
    subitems = split_tcl_list(token, _ZERO_POSITION)
    if len(subitems) != 2 or not is_simple_name(subitems[0].text):
        return None

    default_value = subitems[1].text
    if (
        not default_value
        or not is_simple_name(default_value)
        or default_value.isdigit()
        or default_value.startswith('-')
        or default_value in _DEFAULT_LITERAL_KEYWORDS
    ):
        return CommandArity(min_args=0, max_args=1)
    return None


def _is_safe_inline_optional_literal(token: str) -> bool:
    if len(token) <= 2 or not token.startswith('?') or not token.endswith('?'):
        return False
    inner = token[1:-1]
    return bool(inner) and inner.startswith('-') and '?' not in inner and '...' not in inner


def _has_internal_whitespace(text: str) -> bool:
    return any(char.isspace() for char in text)
