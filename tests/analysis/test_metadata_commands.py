from __future__ import annotations

from pathlib import Path

from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    load_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.metadata_paths import metadata_dir


def test_core_metadata_supports_option_aware_selectors() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.tcl')
    regexp_command = next(
        command
        for command in load_metadata_commands(metadata_path)
        if command.name == 'regexp'
    )
    bind_annotation = next(
        annotation
        for annotation in regexp_command.annotations
        if isinstance(annotation, MetadataBind)
    )

    selected = select_argument_indices(
        bind_annotation.selector,
        ('-start', '1', '-indices', '(..)(..)', 'text', 'match', 'left', 'right'),
        regexp_command.options,
    )

    assert selected == (5, 6, 7)


def test_core_metadata_option_selectors_allow_dynamic_positionals() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.tcl')
    regexp_command = next(
        command
        for command in load_metadata_commands(metadata_path)
        if command.name == 'regexp'
    )
    bind_annotation = next(
        annotation
        for annotation in regexp_command.annotations
        if isinstance(annotation, MetadataBind)
    )

    selected = select_argument_indices(
        bind_annotation.selector,
        ('-start', None, None, None, 'match'),
        regexp_command.options,
    )

    assert selected == (4,)


def test_core_metadata_parses_return_options() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.tcl')
    return_command = next(
        command
        for command in load_metadata_commands(metadata_path)
        if command.name == 'return'
    )

    assert [(option.name, option.kind) for option in return_command.options] == [
        ('-code', 'value'),
        ('-errorcode', 'value'),
        ('-errorinfo', 'value'),
        ('-level', 'value'),
        ('-options', 'value'),
        ('--', 'stop'),
    ]
