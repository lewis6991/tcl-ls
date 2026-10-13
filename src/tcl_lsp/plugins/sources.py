from __future__ import annotations

from collections.abc import Callable

from tcl_lsp.analysis.facts.parsing import (
    ListItem,
    split_tcl_list,
)
from tcl_lsp.analysis.facts.values import VariableSource
from tcl_lsp.common import Position, Span

_ZERO_POSITION = Position(0, 0, 0)
_LIST_ESCAPES = str.maketrans(
    {
        '\\': '\\\\',
        ' ': '\\ ',
        '\t': '\\t',
        '\n': '\\n',
        '\r': '\\r',
        '\v': '\\v',
        '\f': '\\f',
        '{': '\\{',
        '}': '\\}',
        '"': '\\"',
    }
)


def tcl_list(values: tuple[str, ...] | list[str]) -> str:
    """Encode data as a Tcl list without evaluating it."""
    return ' '.join(value.translate(_LIST_ESCAPES) if value else '{}' for value in values)


def list_words(text: str) -> list[str]:
    return [item.text for item in split_tcl_list(text, _ZERO_POSITION, strict=True)]


class PluginSources:
    """Read-only source items available to one plugin invocation.

    Tokens can only refer to literals supplied by analysis, their list items,
    or slices of those items. Plugins cannot invent source locations.
    Dictionaries expose raw text for inspection; their IDs identify the stored
    source, which cannot be changed by editing dictionary fields.
    """

    def __init__(
        self,
        *,
        word_source: Callable[[int], ListItem | None],
        variable_source: VariableSource,
    ) -> None:
        self._word_source = word_source
        self._variable_source = variable_source
        self._sources: dict[str, ListItem] = {}
        self._tokens: dict[ListItem, str] = {}

    def item(self, token: str) -> ListItem:
        source = self._sources.get(token)
        if source is None:
            raise ValueError(f'Unknown plugin source `{token}`.')
        return source

    def value(self, source: ListItem | None) -> str:
        if source is None:
            return ''
        token = self._tokens.get(source)
        if token is None:
            token = f's{len(self._sources)}'
            self._sources[token] = source
            self._tokens[source] = token
        grouped = '1' if source.span.start != source.content_start else '0'
        return tcl_list(['id', token, 'text', source.text, 'grouped', grouped])

    def _source(self, value: str) -> ListItem:
        fields = list_words(value)
        if len(fields) % 2:
            raise ValueError('Plugin values must be source dictionaries.')
        settings = dict(zip(fields[::2], fields[1::2], strict=True))
        return self.item(settings.get('id', ''))

    def query(self, words: tuple[str, ...]) -> str:
        if not words:
            raise ValueError('Missing plugin query operation.')
        operation, *arguments = words
        if operation == 'word' and len(arguments) == 1:
            index = int(arguments[0])
            if index < 1:
                raise ValueError('Plugin word indices start at 1.')
            return self.value(self._word_source(index - 1))
        if operation == 'variable' and len(arguments) == 1:
            return self.value(self._variable_source(arguments[0]))
        if operation == 'source-list-items' and len(arguments) == 1:
            source = self._source(arguments[0])
            items = split_tcl_list(source.text, source.content_start, strict=True)
            return tcl_list([self.value(item) for item in items])
        if operation == 'slice' and len(arguments) == 3:
            source = self._source(arguments[0])
            start = int(arguments[1])
            end = len(source.text) if arguments[2] == 'end' else int(arguments[2])
            if not 0 <= start <= end <= len(source.text):
                raise ValueError('Plugin source slice is out of range.')
            text = source.text[start:end]
            position = source.content_start.advance(source.text[:start])
            return self.value(ListItem(text, Span(position, position.advance(text)), position))
        raise ValueError(f'Invalid plugin query `{operation}`.')
