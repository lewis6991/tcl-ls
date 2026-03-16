from __future__ import annotations

from pathlib import Path

from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataSelector,
    MetadataValueSet,
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


def test_core_metadata_option_selectors_skip_unstable_expansion_tails() -> None:
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
        ('-indices', '(..)(..)', None, 'match'),
        regexp_command.options,
        (False, False, True, False),
    )

    assert selected is None


def test_argument_selectors_allow_fixed_positions_before_late_expansion() -> None:
    selected = select_argument_indices(
        MetadataSelector(start_index=0, all_remaining=False, list_mode=False, after_options=False),
        ('gurka', None),
        (),
        (False, True),
    )

    assert selected == (0,)


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


def test_metadata_parses_keyword_value_sets(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'keywords.tcl'
    metadata_path.write_text(
        '# test metadata\n'
        'meta command demo {flag value} {\n'
        '    keyword 2 alpha beta gamma\n'
        '}\n',
        encoding='utf-8',
    )

    command = load_metadata_commands(metadata_path)[0]

    assert command.value_sets == (
        MetadataValueSet(
            selector=command.value_sets[0].selector,
            kind='keyword',
            values=('alpha', 'beta', 'gamma'),
        ),
    )
    assert command.value_sets[0].selector.start_index == 1


def test_core_metadata_derives_subcommand_value_sets() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.tcl')
    info_command = next(
        command
        for command in load_metadata_commands(metadata_path)
        if command.name == 'info'
    )

    subcommand_values = next(
        value_set.values
        for value_set in info_command.value_sets
        if value_set.kind == 'subcommand'
    )

    assert 'args' in subcommand_values
    assert 'body' in subcommand_values
    assert 'class' in subcommand_values


def test_builtin_metadata_exposes_derived_subcommand_value_sets() -> None:
    from tcl_lsp.analysis.builtins import builtin_command

    namespace_ensemble = builtin_command('namespace ensemble')
    assert namespace_ensemble is not None

    subcommand_values = next(
        value_set.values
        for value_set in namespace_ensemble.overloads[0].value_sets
        if value_set.kind == 'subcommand'
    )

    assert subcommand_values == ('create', 'configure', 'exists')
