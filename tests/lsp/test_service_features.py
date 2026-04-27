from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.builtins import builtin_command
from tests.lsp.helpers import (
    MAIN_URI,
)
from tests.lsp_service import LanguageService


def test_language_service_does_not_resolve_unrelated_open_documents(
    service: LanguageService,
) -> None:
    service.open_document('file:///defs.tcl', 'proc greet {name} {puts $name}\n', 1)
    diagnostics = service.open_document('file:///use.tcl', 'greet World\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert service.definition('file:///use.tcl', 0, 1) == ()
    assert service.hover('file:///use.tcl', 0, 1) is None

    references = service.references('file:///defs.tcl', 0, 5)
    assert {(location.uri, location.range.start.line) for location in references} == {
        ('file:///defs.tcl', 0),
    }


def test_language_service_references_include_ambiguous_shared_procedure_calls(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    defs_a = workspace / 'defs_a.tcl'
    defs_b = workspace / 'defs_b.tcl'
    main = workspace / 'main.tcl'
    defs_a.write_text('proc ::app::hook {} {return a}\n', encoding='utf-8')
    defs_b.write_text('proc ::app::hook {} {return b}\n', encoding='utf-8')
    main.write_text(
        'source [file join [file dirname [info script]] defs_a.tcl]\n'
        'source [file join [file dirname [info script]] defs_b.tcl]\n'
        '::app::hook\n',
        encoding='utf-8',
    )

    service.open_document(main.as_uri(), main.read_text(encoding='utf-8'), 1)
    references = service.references(defs_a.as_uri(), 0, 12)

    assert {(location.uri, location.range.start.line) for location in references} == {
        (defs_a.as_uri(), 0),
        (defs_b.as_uri(), 0),
        (main.as_uri(), 2),
    }


def test_language_service_hover_includes_proc_comment_blocks(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        '# Greets a user by name.\n# Returns nothing.\nproc greet {name} {puts $name}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet World\n',
        1,
    )

    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'


def test_language_service_definition_resolves_builtin_command_metadata(
    service: LanguageService,
) -> None:
    service.open_document(MAIN_URI, 'set value 1\n', 1)

    builtin = builtin_command('set')
    assert builtin is not None

    definition_locations = service.definition(MAIN_URI, 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0] == builtin.overloads[0].location


def test_language_service_definition_returns_all_builtin_overloads(
    service: LanguageService,
) -> None:
    service.open_document(MAIN_URI, 'after 100\n', 1)

    builtin = builtin_command('after')
    assert builtin is not None

    definition_locations = service.definition(MAIN_URI, 0, 1)
    assert definition_locations == tuple(overload.location for overload in builtin.overloads)


def test_language_service_definition_prefers_project_builtin_override_metadata(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / '.tcl-ls'
    plugin_root.mkdir()
    override_path = plugin_root / 'override.meta.tcl'
    override_path.write_text('meta module Tcl\nmeta command clock {args}\n', encoding='utf-8')
    (tmp_path / 'tcllsrc.tcl').write_text('plugin-path .tcl-ls\n', encoding='utf-8')

    source_path = tmp_path / 'main.tcl'
    source_text = 'clock foo\n'
    source_path.write_text(source_text, encoding='utf-8')

    assert service.open_document(source_path.as_uri(), source_text, 1) == ()

    definition_locations = service.definition(source_path.as_uri(), 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == override_path.as_uri()

    hover = service.hover(source_path.as_uri(), 0, 1)
    assert hover is not None
    assert hover.contents == 'builtin command clock {args}'


def test_language_service_definition_resolves_global_variable_links(
    service: LanguageService,
) -> None:
    service.open_document(
        MAIN_URI,
        'set shared 0\nproc run {} {\n    global shared\n    incr shared\n    puts $shared\n}\n',
        1,
    )

    definition_locations = service.definition(MAIN_URI, 4, 11)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 4

    hover = service.hover(MAIN_URI, 4, 11)
    assert hover is not None
    assert hover.contents == 'set shared'


def test_language_service_definition_resolves_namespace_variable_links(
    service: LanguageService,
) -> None:
    service.open_document(
        MAIN_URI,
        'namespace eval app {\n'
        '    variable counter 0\n'
        '    proc run {} {\n'
        '        variable counter\n'
        '        puts $counter\n'
        '    }\n'
        '}\n',
        1,
    )

    definition_locations = service.definition(MAIN_URI, 4, 16)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == 1
    assert definition_locations[0].range.start.character == 13

    hover = service.hover(MAIN_URI, 4, 16)
    assert hover is not None
    assert hover.contents == 'variable counter'


def test_language_service_definition_resolves_variable_alias_sites(
    service: LanguageService,
) -> None:
    service.open_document(
        MAIN_URI,
        'namespace eval app {\n'
        '    variable counter\n'
        '    if {![info exists counter]} { set counter 0 }\n'
        '    proc run {} {\n'
        '        variable counter\n'
        '    }\n'
        '}\n',
        1,
    )

    alias_definition_locations = service.definition(MAIN_URI, 4, 18)
    assert len(alias_definition_locations) == 1
    assert alias_definition_locations[0].uri == MAIN_URI
    assert alias_definition_locations[0].range.start.line == 1
    assert alias_definition_locations[0].range.start.character == 13

    alias_hover = service.hover(MAIN_URI, 4, 18)
    assert alias_hover is not None
    assert alias_hover.contents == 'variable counter'

    namespace_write_definition_locations = service.definition(MAIN_URI, 2, 38)
    assert len(namespace_write_definition_locations) == 1
    assert namespace_write_definition_locations[0].uri == MAIN_URI
    assert namespace_write_definition_locations[0].range.start.line == 1
    assert namespace_write_definition_locations[0].range.start.character == 13


def test_language_service_definition_resolves_dynamic_set_targets_from_foreach_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {strategy} {\n'
        '    foreach v {mode run_limit engines} {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    return_line = source_text.splitlines()[4]
    target_character = return_line.index('$engines') + 1
    definition_locations = service.definition(MAIN_URI, 4, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == 2
    assert definition_locations[0].range.start.character == source_text.splitlines()[2].index('$v')

    hover = service.hover(MAIN_URI, 4, target_character)
    assert hover is not None
    assert hover.contents == 'set engines'

    binding_hover = service.hover(MAIN_URI, 2, source_text.splitlines()[2].index('$v') + 1)
    assert binding_hover is not None
    assert binding_hover.contents == 'set mode\nset run_limit\nset engines'


def test_language_service_definition_resolves_dynamic_set_targets_from_variable_backed_foreach_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {strategy} {\n'
        '    set names {mode run_limit engines}\n'
        '    set slots $names\n'
        '    foreach v $slots {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    return_line = source_text.splitlines()[6]
    target_character = return_line.index('$engines') + 1
    definition_locations = service.definition(MAIN_URI, 6, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == 4
    assert definition_locations[0].range.start.character == source_text.splitlines()[4].index('$v')

    hover = service.hover(MAIN_URI, 6, target_character)
    assert hover is not None
    assert hover.contents == 'set engines'


def test_language_service_preserves_switch_branch_list_body_positions_after_continuations(
    service: LanguageService,
) -> None:
    source_text = (
        'proc helper args {return ok}\n'
        'proc run {mode a b c d e} {\n'
        '    switch -regexp $mode {\n'
        '        "prepare" {\n'
        '            helper \\\n'
        '                -a $a \\\n'
        '                -b $b \\\n'
        '                -c $c \\\n'
        '                -d $d \\\n'
        '                -e $e\n'
        '        }\n'
        '        "mode_alpha" -\n'
        '        "mode_beta" -\n'
        '        "mode_gamma" -\n'
        '        "mode_[12]" {\n'
        '            set mapped_mode [switch $mode {\n'
        '              mode_1  {concat mode_beta}\n'
        '              mode_2  {concat mode_gamma}\n'
        '              default {concat $mode}\n'
        '            }]\n'
        '            puts $mapped_mode\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    set_line = source_text.splitlines().index('            set mapped_mode [switch $mode {')
    switch_character = source_text.splitlines()[set_line].index('switch') + 1
    hover = service.hover(MAIN_URI, set_line, switch_character)
    assert hover is not None
    assert hover.contents.startswith('builtin command switch')

    puts_line = source_text.splitlines().index('            puts $mapped_mode')
    target_character = source_text.splitlines()[puts_line].index('$mapped_mode') + 1
    definition_locations = service.definition(MAIN_URI, puts_line, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == set_line
    assert definition_locations[0].range.start.character == (
        source_text.splitlines()[set_line].index('mapped_mode')
    )


def test_language_service_hover_shows_branch_narrowed_values(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {} {\n'
        '    foreach kind {prove lint scan} {\n'
        '        if {$kind eq "prove"} {\n'
        '            puts $kind\n'
        '        } elseif {$kind eq "lint"} {\n'
        '            puts $kind\n'
        '        } else {\n'
        '            puts $kind\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    then_hover = service.hover(MAIN_URI, 3, source_text.splitlines()[3].index('$kind') + 1)
    assert then_hover is not None
    assert then_hover.contents == 'foreach kind: "prove"'

    elseif_hover = service.hover(MAIN_URI, 5, source_text.splitlines()[5].index('$kind') + 1)
    assert elseif_hover is not None
    assert elseif_hover.contents == 'foreach kind: "lint"'

    else_hover = service.hover(MAIN_URI, 7, source_text.splitlines()[7].index('$kind') + 1)
    assert else_hover is not None
    assert else_hover.contents == 'foreach kind: "scan"'


def test_language_service_narrows_literal_regexp_switch_branch_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {mode} {\n'
        '    switch -regexp $mode {\n'
        '        "alpha" -\n'
        '        "beta" -\n'
        '        "gamma" {\n'
        '            switch $mode {\n'
        '                "alpha" { return first }\n'
        '                "beta" { return second }\n'
        '                "gamma" { return third }\n'
        '            }\n'
        '        }\n'
        '        "[de]lta" {\n'
        '            return fallback\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    inner_switch_line = source_text.splitlines().index('            switch $mode {')
    inner_switch_character = source_text.splitlines()[inner_switch_line].index('$mode') + 1
    hover = service.hover(MAIN_URI, inner_switch_line, inner_switch_character)
    assert hover is not None
    assert hover.contents == 'parameter mode: "alpha" | "beta" | "gamma"'


def test_language_service_hover_shows_switch_assignment_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {mode} {\n'
        '    switch -regexp $mode {\n'
        '        "direct_alpha" -\n'
        '        "direct_beta" -\n'
        '        "mode_1" -\n'
        '        "mode_2" {\n'
        '            set mapped_mode [switch $mode {\n'
        '                mode_1 {concat target_alpha}\n'
        '                mode_2 {concat target_beta}\n'
        '                default {concat $mode}\n'
        '            }]\n'
        '            puts $mapped_mode\n'
        '        }\n'
        '        "[fg].*" {\n'
        '            return fallback\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    binding_line = source_text.splitlines().index('            set mapped_mode [switch $mode {')
    binding_character = source_text.splitlines()[binding_line].index('mapped_mode') + 1
    binding_hover = service.hover(MAIN_URI, binding_line, binding_character)
    assert binding_hover is not None
    assert (
        binding_hover.contents
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )

    reference_line = source_text.splitlines().index('            puts $mapped_mode')
    reference_character = source_text.splitlines()[reference_line].index('$mapped_mode') + 1
    reference_hover = service.hover(MAIN_URI, reference_line, reference_character)
    assert reference_hover is not None
    assert (
        reference_hover.contents
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )


def test_language_service_hover_shows_expr_ternary_assignment_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {} {\n'
        '    foreach bg {0 1} {\n'
        '        set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'
        '        puts $bg_opt\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(MAIN_URI, source_text, 1) == ()

    hover = service.hover(MAIN_URI, 3, source_text.splitlines()[3].index('$bg_opt') + 1)
    assert hover is not None
    assert hover.contents == 'set bg_opt: "a" | "b"'

    binding_hover = service.hover(MAIN_URI, 2, source_text.splitlines()[2].index('bg_opt') + 1)
    assert binding_hover is not None
    assert binding_hover.contents == 'set bg_opt: "a" | "b"'


def test_language_service_rename_updates_proc_declaration_and_calls(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {name} {return $name}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet World\n',
        1,
    )

    edits = service.rename(main_uri, 1, 1, 'welcome')

    assert edits is not None
    assert set(edits) == {helper_path.as_uri(), main_uri}
    assert edits[helper_path.as_uri()][0].span.start.line == 0
    assert edits[helper_path.as_uri()][0].span.start.character == 5
    assert edits[helper_path.as_uri()][0].new_text == 'welcome'
    assert edits[main_uri][0].span.start.line == 1
    assert edits[main_uri][0].span.start.character == 0
    assert edits[main_uri][0].new_text == 'welcome'


def test_language_service_rename_updates_variable_bindings_and_references(
    service: LanguageService,
) -> None:
    service.open_document(
        MAIN_URI,
        'proc run {value} {\n    set local $value\n    puts $local\n}\n',
        1,
    )

    edits = service.rename(MAIN_URI, 1, 9, 'item')

    assert edits is not None
    assert tuple(edits) == (MAIN_URI,)
    assert [
        (edit.span.start.line, edit.span.start.character, edit.new_text) for edit in edits[MAIN_URI]
    ] == [
        (1, 8, 'item'),
        (2, 9, '$item'),
    ]


@pytest.mark.parametrize(
    ('text', 'character', 'builtin_name'),
    [
        ('namespace current\n', 11, 'namespace current'),
        ('dict get {a 1} a\n', 6, 'dict get'),
        ('trace add command foo delete cb\n', 12, 'trace add command'),
        ('binary encode base64 data\n', 15, 'binary encode base64'),
    ],
)
def test_language_service_definition_resolves_builtin_subcommand_metadata(
    service: LanguageService,
    text: str,
    character: int,
    builtin_name: str,
) -> None:
    service.open_document(MAIN_URI, text, 1)

    builtin = builtin_command(builtin_name)
    assert builtin is not None
    assert len(builtin.overloads) == 1

    definition_locations = service.definition(MAIN_URI, 0, character)
    assert len(definition_locations) == 1
    assert definition_locations[0] == builtin.overloads[0].location


def test_language_service_analyzes_catch_bodies_and_result_variables(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        MAIN_URI,
        'proc helper {} {return ok}\n'
        'proc run {} {\n'
        '    catch {\n'
        '        set local [helper]\n'
        '    } message options\n'
        '    puts $message\n'
        '    puts $options\n'
        '    puts $local\n'
        '}\n',
        1,
    )

    assert diagnostics == ()


def test_language_service_resolves_references_inside_braced_if_conditions(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        MAIN_URI,
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {$flag && [helper]} {\n'
        '        return ok\n'
        '    }\n'
        '}\n',
        1,
    )

    assert diagnostics == ()

    hover = service.hover(MAIN_URI, 2, 9)
    assert hover is not None
    assert hover.contents == 'parameter flag'

    definition_locations = service.definition(MAIN_URI, 2, 18)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == MAIN_URI
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 5


def test_language_service_does_not_report_meta_guard_commands_as_unresolved(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        'file:///meta_file.tcl',
        'if {[llength [info commands meta]] == 0} {\n'
        '    proc meta {args} {}\n'
        '}\n'
        '# Builtin metadata entry.\n'
        'meta command after {ms}\n',
        1,
    )

    assert diagnostics == ()
