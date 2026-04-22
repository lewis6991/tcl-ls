from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.builtins import (
    annotated_metadata_commands_for_packages,
    builtin_command,
    builtin_commands_by_package,
)
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataContext,
    MetadataPackage,
    MetadataPlugin,
    MetadataProcedure,
    MetadataSelector,
    MetadataSource,
    load_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.metadata_paths import bundled_metadata_dir, create_metadata_registry


def test_core_metadata_supports_option_aware_selectors() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
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


def test_core_metadata_option_selectors_reject_dynamic_option_prefixes() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
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

    assert selected is None


def test_core_metadata_option_selectors_skip_unstable_expansion_tails() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
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


def test_argument_selectors_support_stepped_last_ranges() -> None:
    selected = select_argument_indices(
        MetadataSelector(
            start_index=0,
            all_remaining=False,
            list_mode=False,
            after_options=False,
            step=2,
            end_index=1,
            end_from_end=True,
        ),
        ('a', 'b', 'c', 'd', 'e'),
        (),
    )

    assert selected == (0, 2)


def test_argument_selectors_reject_relative_tails_after_expansion() -> None:
    selected = select_argument_indices(
        MetadataSelector(
            start_index=0,
            all_remaining=False,
            list_mode=False,
            after_options=False,
            start_from_end=True,
        ),
        ('head', 'body'),
        (),
        (True, False),
    )

    assert selected is None


def test_core_metadata_leaves_return_unannotated() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    return_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'return'
    )

    assert return_command.options == ()


def test_core_metadata_derives_subcommands() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    info_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'info'
    )

    assert 'args' in info_command.subcommands
    assert 'body' in info_command.subcommands
    assert 'class' in info_command.subcommands


def test_core_metadata_parses_foreach_loop_selectors() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcl.meta.tcl')
    foreach_command = next(
        command for command in load_metadata_commands(metadata_path) if command.name == 'foreach'
    )
    bind_annotation = next(
        annotation
        for annotation in foreach_command.annotations
        if isinstance(annotation, MetadataBind)
    )
    body_annotation = next(
        annotation
        for annotation in foreach_command.annotations
        if isinstance(annotation, MetadataContext)
    )

    assert bind_annotation.selector.list_mode is True
    assert bind_annotation.selector.step == 2
    assert bind_annotation.selector.start_index == 0
    assert bind_annotation.selector.end_index == 1
    assert bind_annotation.selector.end_from_end is True
    assert body_annotation.context_name == 'tcl'
    assert body_annotation.owner_selector is None
    assert body_annotation.body_selector.start_from_end is True
    assert select_argument_indices(
        bind_annotation.selector,
        ('item', 'left', 'weight', 'right', 'body'),
        (),
    ) == (0, 2)
    assert body_annotation.body_selector.start_from_end is True
    assert select_argument_indices(
        body_annotation.body_selector,
        ('item', 'left', 'weight', 'right', 'body'),
        (),
    ) == (4,)


def test_builtin_metadata_exposes_nested_and_derived_subcommands() -> None:
    binary_decode = builtin_command('binary decode')
    assert binary_decode is not None

    namespace_ensemble = builtin_command('namespace ensemble')
    assert namespace_ensemble is not None

    assert binary_decode.overloads[0].subcommands == ('base64', 'hex', 'uuencode')
    assert namespace_ensemble.overloads[0].subcommands == ('create', 'configure', 'exists')


def test_core_metadata_models_meta_as_ensemble() -> None:
    meta_builtin = builtin_command('meta')
    meta_command_builtin = builtin_command('meta command')
    meta_language_builtin = builtin_command('meta language')
    meta_module_builtin = builtin_command('meta module')

    assert meta_builtin is not None
    assert meta_command_builtin is not None
    assert meta_language_builtin is not None
    assert meta_module_builtin is not None
    assert meta_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_command_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_language_builtin.metadata_path_name == 'meta.meta.tcl'
    assert meta_module_builtin.metadata_path_name == 'meta.meta.tcl'

    assert meta_builtin.overloads[0].subcommands == ('module', 'command', 'language')

    assert tuple(overload.signature for overload in meta_command_builtin.overloads) == (
        'meta command {name shape}',
        'meta command {name shape body}',
        'meta command {name variants body}',
    )
    assert any(
        overload.arity is not None and overload.arity.accepts(2)
        for overload in meta_command_builtin.overloads
    )
    assert any(
        overload.arity is not None and overload.arity.accepts(3)
        for overload in meta_command_builtin.overloads
    )
    assert meta_module_builtin.overloads[0].arity is not None
    assert meta_module_builtin.overloads[0].arity.accepts(1) is True


def test_project_metadata_overrides_matching_bundled_builtin_commands(tmp_path: Path) -> None:
    override_path = tmp_path / 'override.meta.tcl'
    override_path.write_text('meta module Tcl\nmeta command clock {args}\n', encoding='utf-8')
    metadata_registry = create_metadata_registry((tmp_path,))
    builtin = builtin_command('clock', metadata_registry=metadata_registry)

    assert builtin is not None
    assert len(builtin.overloads) == 1
    overload = builtin.overloads[0]
    assert overload.signature == 'clock {args}'
    assert builtin.metadata_path_name == 'override.meta.tcl'
    assert overload.location.uri == override_path.as_uri()


def test_project_metadata_override_replaces_bundled_subcommand_tree(tmp_path: Path) -> None:
    override_path = tmp_path / 'override.meta.tcl'
    override_path.write_text(
        'meta module Tcl\nmeta command namespace {args}\n',
        encoding='utf-8',
    )
    metadata_registry = create_metadata_registry((tmp_path,))
    namespace_command = builtin_command('namespace', metadata_registry=metadata_registry)
    namespace_eval = builtin_command('namespace eval', metadata_registry=metadata_registry)

    assert namespace_command is not None
    assert namespace_command.metadata_path_name == 'override.meta.tcl'
    assert namespace_eval is None


def test_project_metadata_same_root_rejects_conflicting_annotations(tmp_path: Path) -> None:
    (tmp_path / 'a.meta.tcl').write_text(
        'meta module Tcl\nmeta command regexp {args} {\n    bind 1 set\n}\n',
        encoding='utf-8',
    )
    (tmp_path / 'b.meta.tcl').write_text(
        'meta module Tcl\nmeta command regexp {args} {\n    bind 2 set\n}\n',
        encoding='utf-8',
    )
    metadata_registry = create_metadata_registry((tmp_path,))

    with pytest.raises(
        RuntimeError,
        match='Conflicting metadata annotations',
    ):
        annotated_metadata_commands_for_packages(
            frozenset(),
            metadata_registry=metadata_registry,
        )


def test_tcloo_metadata_parses_embedded_context_annotations() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcl8.6/tcloo.meta.tcl')
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
    assert context_annotation.owner_selector is not None
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
    assert procedure_annotation.member_name_selector is not None
    assert procedure_annotation.member_name_selector.start_index == 0
    assert procedure_annotation.parameter_selector is not None
    assert procedure_annotation.parameter_selector.start_index == 1
    assert procedure_annotation.body_selector is not None
    assert procedure_annotation.body_selector.start_index == 2
    assert procedure_annotation.body_context == 'tcloo-method'

    method_body_command = next(
        command
        for command in commands
        if command.context_name == 'tcloo-method' and command.name == 'my'
    )
    assert method_body_command.context_fallback == 'tcl'


def test_tepam_metadata_parses_plugin_annotations() -> None:
    metadata_path = bundled_metadata_dir() / Path('tcllib/tepam.meta.tcl')
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
    assert plugin_annotation.script_path == (
        bundled_metadata_dir() / Path('tcllib/tepam.tcl')
    ).resolve(strict=False)
    assert plugin_annotation.proc_name == '::tcl_lsp::plugins::tepam::statementWords'


def test_builtin_metadata_ignores_context_commands() -> None:
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
        'meta language sample {\n    command {my variable} {name args}\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='Metadata command entries must use single command names',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_rejects_incomplete_top_level_meta_entries(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'bad.meta.tcl'
    metadata_path.write_text('meta\n', encoding='utf-8')

    with pytest.raises(
        RuntimeError,
        match='Metadata top-level entries must be',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_rejects_bare_shape_with_top_level_body(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'bad.meta.tcl'
    metadata_path.write_text('meta command interp hello {}\n', encoding='utf-8')

    with pytest.raises(
        RuntimeError,
        match='must use a braced shape when a clause body is present',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_rejects_bind_without_inferable_kind(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'bad_bind.meta.tcl'
    metadata_path.write_text(
        'meta command demo {name} {\n    bind 1\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='requires an explicit binding kind',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_parses_language_entries_and_enter_annotations(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'sample.meta.tcl'
    metadata_path.write_text(
        'meta language sample {\n'
        '    command step {body} {\n'
        '        bind 1 set\n'
        '    }\n'
        '}\n'
        'meta command run {body} {\n'
        '    enter sample body 1\n'
        '}\n',
        encoding='utf-8',
    )

    commands = load_metadata_commands(metadata_path)
    run_command = next(command for command in commands if command.name == 'run')
    enter_annotation = next(
        annotation
        for annotation in run_command.annotations
        if isinstance(annotation, MetadataContext)
    )
    language_command = next(
        command
        for command in commands
        if command.context_name == 'sample' and command.name == 'step'
    )

    assert enter_annotation.context_name == 'sample'
    assert enter_annotation.owner_selector is None
    assert enter_annotation.body_selector.start_index == 0
    assert language_command.signature == 'body'


def test_metadata_parses_language_fallback_clauses(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'sample.meta.tcl'
    metadata_path.write_text(
        'meta language sample {\n    fallback tcl\n    command step {body}\n}\n',
        encoding='utf-8',
    )

    commands = load_metadata_commands(metadata_path)
    language_command = next(
        command
        for command in commands
        if command.context_name == 'sample' and command.name == 'step'
    )

    assert language_command.context_fallback == 'tcl'


def test_metadata_treats_form_as_regular_shape_without_variants(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'single.meta.tcl'
    metadata_path.write_text(
        'meta command demo {form args} {\n    bind 1 set\n}\n',
        encoding='utf-8',
    )

    command = load_metadata_commands(metadata_path)[0]

    assert command.name == 'demo'
    assert command.signature == 'form args'


def test_metadata_parses_variant_containers(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'forms.meta.tcl'
    metadata_path.write_text(
        'meta command after variants {\n'
        '    form {ms}\n'
        '    form {ms script args} {\n'
        '        bind 2 set\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )

    commands = tuple(
        command for command in load_metadata_commands(metadata_path) if command.name == 'after'
    )

    assert tuple(command.signature for command in commands) == ('ms', 'ms script args')
    bind_annotation = next(
        annotation for annotation in commands[1].annotations if isinstance(annotation, MetadataBind)
    )
    assert bind_annotation.selector.start_index == 1


def test_metadata_rejects_variants_without_form(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'invalid_variants.meta.tcl'
    metadata_path.write_text(
        'meta command root variants {\n    command child {x}\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='variants bodies must declare at least one `form` entry',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_parses_nested_command_declarations(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'nested.meta.tcl'
    metadata_path.write_text(
        'meta command array {subcommand args} {\n'
        '    command get {arrayName ?pattern?}\n'
        '    command set {arrayName list}\n'
        '}\n',
        encoding='utf-8',
    )

    commands = {command.name: command for command in load_metadata_commands(metadata_path)}

    assert commands['array get'].signature == 'arrayName ?pattern?'
    assert commands['array set'].signature == 'arrayName list'


def test_metadata_parses_nested_command_variants(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'nested_variants.meta.tcl'
    metadata_path.write_text(
        'meta command package {subcommand args} {\n'
        '    command require variants {\n'
        '        form {package ?requirement...?}\n'
        '        form {-exact package version}\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )

    commands = tuple(
        command
        for command in load_metadata_commands(metadata_path)
        if command.name == 'package require'
    )

    assert tuple(command.signature for command in commands) == (
        'package ?requirement...?',
        '-exact package version',
    )


def test_metadata_rejects_legacy_subcommand_declarations(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'legacy.meta.tcl'
    metadata_path.write_text(
        'meta command array {subcommand args} {\n    subcommand get {arrayName ?pattern?}\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='Unknown metadata command annotation `subcommand`',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_parses_new_package_and_source_syntax(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'deps.meta.tcl'
    metadata_path.write_text(
        'meta command use-tcloo {args} {\n'
        '    package literal TclOO\n'
        '}\n'
        'meta command use-dynamic {name} {\n'
        '    package select 1\n'
        '}\n'
        'meta command load-local {path} {\n'
        '    source 1 caller\n'
        '}\n'
        'meta command load-relative {path} {\n'
        '    source 1 definition\n'
        '}\n',
        encoding='utf-8',
    )

    commands = {command.name: command for command in load_metadata_commands(metadata_path)}

    fixed_package = next(
        annotation
        for annotation in commands['use-tcloo'].annotations
        if isinstance(annotation, MetadataPackage)
    )
    dynamic_package = next(
        annotation
        for annotation in commands['use-dynamic'].annotations
        if isinstance(annotation, MetadataPackage)
    )
    caller_source = next(
        annotation
        for annotation in commands['load-local'].annotations
        if isinstance(annotation, MetadataSource)
    )
    definition_source = next(
        annotation
        for annotation in commands['load-relative'].annotations
        if isinstance(annotation, MetadataSource)
    )

    assert fixed_package.literal_package == 'TclOO'
    assert fixed_package.selector is None
    assert dynamic_package.selector is not None
    assert dynamic_package.literal_package is None
    assert caller_source.base == 'caller'
    assert definition_source.base == 'definition'


def test_metadata_rejects_non_contiguous_enter_body_selectors(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'invalid_enter.meta.tcl'
    metadata_path.write_text(
        'meta command wrap {a b c d} {\n    enter sample body 1..4 step 2\n}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='must select one contiguous body range',
    ):
        load_metadata_commands(metadata_path)


def test_metadata_parses_tagged_procedure_fields(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'procedure.meta.tcl'
    metadata_path.write_text(
        'meta command demo {name params body} {\n'
        '    procedure {\n'
        '        name select 1\n'
        '        params literal {left right}\n'
        '        body select 3\n'
        '        language sample\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )

    command = load_metadata_commands(metadata_path)[0]
    procedure = next(
        annotation
        for annotation in command.annotations
        if isinstance(annotation, MetadataProcedure)
    )

    assert procedure.member_name_selector is not None
    assert procedure.member_name_selector.start_index == 0
    assert procedure.member_name_literal is None
    assert procedure.parameter_selector is None
    assert procedure.parameter_literal == 'left right'
    assert procedure.body_selector is not None
    assert procedure.body_selector.start_index == 2
    assert procedure.body_context == 'sample'


def test_metadata_rejects_procedure_language_without_body(tmp_path: Path) -> None:
    metadata_path = tmp_path / 'invalid_procedure.meta.tcl'
    metadata_path.write_text(
        'meta command demo {name params} {\n'
        '    procedure {\n'
        '        name select 1\n'
        '        params select 2\n'
        '        language sample\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )

    with pytest.raises(
        RuntimeError,
        match='may only declare `language` when `body` is present',
    ):
        load_metadata_commands(metadata_path)
