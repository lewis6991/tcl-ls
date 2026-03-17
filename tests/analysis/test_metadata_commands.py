from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataContext,
    MetadataPlugin,
    MetadataProcedure,
    MetadataSelector,
    load_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.metadata_paths import metadata_dir


def test_core_metadata_supports_option_aware_selectors() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    regexp_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'regexp'
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
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    regexp_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'regexp'
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
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    regexp_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'regexp'
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


def test_core_metadata_leaves_return_unannotated() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    return_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'return'
    )

    assert return_command.options == ()


def test_core_metadata_derives_subcommands() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    info_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'info'
    )

    assert 'args' in info_command.subcommands
    assert 'body' in info_command.subcommands
    assert 'class' in info_command.subcommands


def test_builtin_metadata_exposes_nested_and_derived_subcommands() -> None:
    from tcl_lsp.analysis.builtins import builtin_command

    binary_decode = builtin_command('binary decode')
    assert binary_decode is not None

    namespace_ensemble = builtin_command('namespace ensemble')
    assert namespace_ensemble is not None

    assert binary_decode.overloads[0].subcommands == ('base64', 'hex', 'uuencode')
    assert namespace_ensemble.overloads[0].subcommands == ('create', 'configure', 'exists')


def test_core_metadata_models_meta_as_ensemble() -> None:
    from tcl_lsp.analysis.builtins import builtin_command

    meta_builtin = builtin_command('meta')
    meta_command_builtin = builtin_command('meta command')
    meta_context_builtin = builtin_command('meta context')
    meta_module_builtin = builtin_command('meta module')

    assert meta_builtin is not None
    assert meta_command_builtin is not None
    assert meta_context_builtin is not None
    assert meta_module_builtin is not None
    assert meta_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_command_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_context_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_module_builtin.metadata_path_name == 'meta.meta.tcl'

    assert meta_builtin.overloads[0].subcommands == ('module', 'command', 'context')

    assert meta_command_builtin.overloads[0].arity is not None
    assert meta_command_builtin.overloads[0].arity.accepts(2) is True
    assert meta_command_builtin.overloads[0].arity.accepts(3) is True
    assert meta_module_builtin.overloads[0].arity is not None
    assert meta_module_builtin.overloads[0].arity.accepts(1) is True


def test_tcloo_metadata_parses_embedded_context_annotations() -> None:
    metadata_path = metadata_dir() / Path('tcl8.6/tcloo.meta.tcl')
    commands = load_metadata_commands(metadata_path)

    define_command = next(
        command
        for command in commands
        if command.context_name is None and command.name == 'oo::define'
    )
    context_annotation = next(
        annotation
        for annotation in define_command.annotations
        if isinstance(annotation, MetadataContext)
    )
    assert context_annotation.context_name == 'tcloo-definition'
    assert context_annotation.owner_selector.start_index == 0
    assert context_annotation.body_selector.start_index == 1
    assert context_annotation.body_selector.all_remaining is True

    method_command = next(
        command
        for command in commands
        if command.context_name == 'tcloo-definition' and command.name == 'method'
    )
    procedure_annotation = next(
        annotation
        for annotation in method_command.annotations
        if isinstance(annotation, MetadataProcedure)
    )
    assert procedure_annotation.member_name_index == 0
    assert procedure_annotation.parameter_index == 1
    assert procedure_annotation.body_index == 2
    assert procedure_annotation.body_context == 'tcloo-method'


def test_tepam_metadata_parses_plugin_annotations() -> None:
    metadata_path = metadata_dir() / Path('tcllib/tepam.meta.tcl')
    commands = load_metadata_commands(metadata_path)

    procedure_command = next(
        command
        for command in commands
        if command.context_name is None and command.name == 'tepam::procedure'
    )
    plugin_annotation = next(
        annotation
        for annotation in procedure_command.annotations
        if isinstance(annotation, MetadataPlugin)
    )
    assert plugin_annotation.script_path == (metadata_dir() / Path('tcllib/tepam.tcl')).resolve(
        strict=False
    )
    assert plugin_annotation.proc_name == '::tcl_lsp::plugins::tepam::statementWords'


def test_builtin_metadata_ignores_context_commands() -> None:
    from tcl_lsp.analysis.builtins import builtin_commands_by_package

    tcloo_commands = builtin_commands_by_package()['TclOO']
    tepam_commands = builtin_commands_by_package()['tepam']
    assert 'oo::define' in tcloo_commands
    assert 'method' not in tcloo_commands
    assert 'my variable' not in tcloo_commands
    assert 'tepam::procedure' in tepam_commands


def test_metadata_rejects_spaced_top_level_command_names(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'bad.meta.tcl'
    metadata_path.write_text(
        '# Invalid deprecated syntax.\nmeta command {file atime} {name ?time?}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='Metadata command entries must use single command names',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_rejects_spaced_context_command_names(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'bad_context.meta.tcl'
    metadata_path.write_text(
        'meta context sample {\n    command {my variable} {name args}\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='Metadata command entries must use single command names',
    ):
        load_metadata_commands(metadata_path)
