from __future__ import annotations

from typing import Literal

from tcl_lsp.analysis.facts.parsing import ListItem, is_simple_name, split_tcl_list
from tcl_lsp.common import Position, Span

type ParameterFormat = Literal['tcl', 'tepam', 'tepam-args']


def procedure_parameter_items(
    text: str, start: Position, parameter_format: ParameterFormat
) -> tuple[ListItem, ...] | None:
    if parameter_format == 'tcl':
        return tuple(split_tcl_list(text, start))

    try:
        items = split_tcl_list(text, start, strict=True)
        if parameter_format == 'tepam':
            if len(items) % 2:
                return None
            arguments: list[ListItem] = []
            for key, value in zip(items[::2], items[1::2], strict=True):
                if key.text == '-args':
                    arguments = split_tcl_list(value.text, value.content_start, strict=True)
            items = arguments

        parameters: list[ListItem] = []
        for item in items:
            fields = split_tcl_list(item.text, item.content_start, strict=True)
            if not fields:
                continue
            name = fields[0].text
            if name in {'-', '--'} or name.startswith('#'):
                continue
            name_start = fields[0].content_start
            if name.startswith('-'):
                name = name[1:]
                name_start = name_start.advance('-')
            if not is_simple_name(name):
                continue
            parameters.append(
                ListItem(
                    text=name,
                    span=Span(start=name_start, end=name_start.advance(name)),
                    content_start=name_start,
                )
            )
        return tuple(parameters)
    except ValueError:
        return None
