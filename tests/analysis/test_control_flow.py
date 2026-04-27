from __future__ import annotations

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.parser import Parser

from .support import analyze_document as _analyze


def test_analysis_tracks_switch_branch_bodies_from_list_form(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_list.tcl',
        'proc helper {} {return ok}\n'
        'proc run {kind} {\n'
        '    switch -- $kind {\n'
        '        alpha {\n'
        '            set local [helper]\n'
        '            puts $local\n'
        '        }\n'
        '        beta -\n'
        '        default {\n'
        '            return done\n'
        '        }\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    local_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'local'
    ]
    assert len(local_references) == 1
    assert local_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_preserves_switch_branch_list_body_positions_after_continuations(
    parser: Parser,
) -> None:
    source = (
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
    snapshot = _analyze(parser, 'file:///switch_list_continuations.tcl', source)
    analysis = snapshot.analysis

    inner_switch_offset = source.index('[switch') + 1
    inner_switch_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name == 'switch'
        and resolution.reference.span.start.offset == inner_switch_offset
    ]
    assert len(inner_switch_resolutions) == 1
    assert inner_switch_resolutions[0].uncertainty.state == 'resolved'

    mapped_mode_reference_offset = source.rindex('$mapped_mode')
    mapped_mode_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name == 'mapped_mode'
        and resolution.reference.span.start.offset == mapped_mode_reference_offset
    ]
    assert len(mapped_mode_resolutions) == 1
    assert mapped_mode_resolutions[0].uncertainty.state == 'resolved'


def test_analysis_tracks_switch_branch_bodies_from_argument_form(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_args.tcl',
        'proc helper {} {return ok}\n'
        'proc run {kind} {\n'
        '    switch -- $kind \\\n'
        '        alpha {\n'
        '            helper\n'
        '        } \\\n'
        '        default {\n'
        '            puts $kind\n'
        '        }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    kind_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'kind'
    ]
    assert len({resolution.reference.span.start.offset for resolution in kind_references}) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in kind_references)
    assert analysis.diagnostics == ()


def test_analysis_tracks_regexp_switch_match_variables(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_regexp.tcl',
        'proc run {value} {\n'
        '    switch -regexp -matchvar matches -indexvar indices -- $value {\n'
        '        {^a(b+)$} {\n'
        '            puts [lindex $matches 1]\n'
        '            puts [lindex $indices 0]\n'
        '        }\n'
        '        default {\n'
        '            puts $matches\n'
        '            puts $indices\n'
        '        }\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['matches'] == 'switch'
    assert bindings_by_name['indices'] == 'switch'

    match_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'matches', 'indices'}
    ]
    unique_match_sites = {
        (resolution.reference.name, resolution.reference.span.start.offset)
        for resolution in match_resolutions
    }
    assert len(unique_match_sites) == 4
    assert {name for name, _ in unique_match_sites} == {'matches', 'indices'}
    assert all(resolution.uncertainty.state == 'resolved' for resolution in match_resolutions)
    assert analysis.diagnostics == ()


def test_analysis_narrows_literal_regexp_switch_branch_domains(parser: Parser) -> None:
    source = (
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
    snapshot = _analyze(parser, 'file:///switch_regexp_domains.tcl', source)

    hover_by_offset = {
        hover.span.start.offset: hover.contents for hover in snapshot.analysis.hovers
    }
    inner_switch_offset = source.index('switch $mode {', source.index('"gamma" {')) + len('switch ')
    assert hover_by_offset[inner_switch_offset] == 'parameter mode: "alpha" | "beta" | "gamma"'


def test_analysis_tracks_switch_assignment_domains(parser: Parser) -> None:
    source = (
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
    snapshot = _analyze(parser, 'file:///switch_assignment_domains.tcl', source)

    hover_by_offset = {
        hover.span.start.offset: hover.contents for hover in snapshot.analysis.hovers
    }
    binding_offset = source.index('mapped_mode')
    assert (
        hover_by_offset[binding_offset]
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )
    mapped_mode_offset = source.rindex('$mapped_mode')
    assert (
        hover_by_offset[mapped_mode_offset]
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )


def test_analysis_tracks_for_while_and_lmap_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///loop_bodies.tcl',
        'proc helper {} {return ok}\n'
        'proc run {items flag} {\n'
        '    for {set i 0} {$i < 2} {incr i} {\n'
        '        helper\n'
        '        puts $i\n'
        '    }\n'
        '    while {$flag} {\n'
        '        set flag 0\n'
        '        helper\n'
        '    }\n'
        '    lmap item $items {\n'
        '        helper\n'
        '        puts $item\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 3
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'flag', 'i', 'item', 'items'}
    }
    assert {name for name, _ in variable_resolutions} == {'flag', 'i', 'item', 'items'}
    assert set(variable_resolutions.values()) == {'resolved'}
    assert analysis.diagnostics == ()


def test_analysis_tracks_multi_source_foreach_and_lmap_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///multi_loop_pairs.tcl',
        'proc helper {} {return ok}\n'
        'proc run {left right} {\n'
        '    foreach item $left weight $right {\n'
        '        helper\n'
        '        puts $item\n'
        '        puts $weight\n'
        '    }\n'
        '    lmap value $left code $right {\n'
        '        helper\n'
        '        list $value $code\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['value'] == 'lmap'
    assert bindings_by_name['code'] == 'lmap'
    assert bindings_by_name['item'] == 'foreach'
    assert bindings_by_name['weight'] == 'foreach'

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'item', 'weight', 'value', 'code', 'left', 'right'}
    }
    assert {name for name, _ in variable_resolutions} == {
        'item',
        'weight',
        'value',
        'code',
        'left',
        'right',
    }
    assert set(variable_resolutions.values()) == {'resolved'}
    assert analysis.diagnostics == ()


def test_analysis_infers_dynamic_set_targets_from_foreach_domains(parser: Parser) -> None:
    source = (
        'proc run {strategy} {\n'
        '    foreach v {mode run_limit engines} {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n'
    )
    snapshot = _analyze(
        parser,
        'file:///dynamic_set_targets.tcl',
        source,
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['mode'] == 'set'
    assert bindings_by_name['run_limit'] == 'set'
    assert bindings_by_name['engines'] == 'set'

    variable_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'mode', 'run_limit', 'engines'}
    }
    assert variable_resolutions == {
        'mode': 'resolved',
        'run_limit': 'resolved',
        'engines': 'resolved',
    }
    assert not any(diagnostic.code == 'unresolved-variable' for diagnostic in analysis.diagnostics)

    source_lines = source.splitlines(keepends=True)
    dynamic_target_offset = (
        len(source_lines[0]) + len(source_lines[1]) + source_lines[2].index('$v')
    )
    matching_hovers = [
        hover for hover in analysis.hovers if hover.span.start.offset == dynamic_target_offset
    ]
    assert (
        min(
            matching_hovers,
            key=lambda hover: hover.span.end.offset - hover.span.start.offset,
        ).contents
        == 'set mode\nset run_limit\nset engines'
    )


def test_analysis_infers_dynamic_set_targets_from_variable_backed_foreach_domains(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_set_targets_from_list_variables.tcl',
        'proc run {strategy} {\n'
        '    set names {mode run_limit engines}\n'
        '    set slots $names\n'
        '    foreach v $slots {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['mode'] == 'set'
    assert bindings_by_name['run_limit'] == 'set'
    assert bindings_by_name['engines'] == 'set'

    variable_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'mode', 'run_limit', 'engines'}
    }
    assert variable_resolutions == {
        'mode': 'resolved',
        'run_limit': 'resolved',
        'engines': 'resolved',
    }
    assert not any(diagnostic.code == 'unresolved-variable' for diagnostic in analysis.diagnostics)


def test_analysis_resolves_dynamic_variable_sites_from_exact_value_domains(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_variable_sites.tcl',
        'proc run {} {\n'
        '    set name counter\n'
        '    set alias $name\n'
        '    set $alias 1\n'
        '    if {[info exists $name]} {\n'
        '        set value [set $alias]\n'
        '    }\n'
        '    unset $name\n'
        '}\n',
    )
    analysis = snapshot.analysis

    counter_sites = {
        resolution.reference.span.start.offset: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'counter'
    }
    assert len(counter_sites) == 3
    assert set(counter_sites.values()) == {'resolved'}
    assert not any(diagnostic.code == 'unresolved-variable' for diagnostic in analysis.diagnostics)


def test_analysis_does_not_infer_dynamic_targets_from_unknown_value_domains(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_unknown_targets.tcl',
        'proc run {strategy names} {\n'
        '    foreach v $names {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return $engines\n'
        '}\n',
    )

    unresolved_variables = [
        diagnostic
        for diagnostic in snapshot.analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    ]
    assert len(unresolved_variables) == 1
    assert unresolved_variables[0].message == 'Unresolved variable `engines`.'


def test_analysis_shows_branch_narrowed_values_in_variable_hovers(parser: Parser) -> None:
    source = (
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
    snapshot = _analyze(parser, 'file:///if_branch_narrowing.tcl', source)

    hover_by_offset = {
        hover.span.start.offset: hover.contents for hover in snapshot.analysis.hovers
    }
    source_lines = source.splitlines(keepends=True)
    line_offsets: list[int] = []
    total_offset = 0
    for line in source_lines:
        line_offsets.append(total_offset)
        total_offset += len(line)

    then_offset = line_offsets[3] + source_lines[3].index('$kind')
    elseif_offset = line_offsets[5] + source_lines[5].index('$kind')
    else_offset = line_offsets[7] + source_lines[7].index('$kind')

    assert hover_by_offset[then_offset] == 'foreach kind: "prove"'
    assert hover_by_offset[elseif_offset] == 'foreach kind: "lint"'
    assert hover_by_offset[else_offset] == 'foreach kind: "scan"'


def test_analysis_tracks_expr_ternary_assignment_domains(parser: Parser) -> None:
    source = (
        'proc run {} {\n'
        '    foreach bg {0 1} {\n'
        '        set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'
        '        puts $bg_opt\n'
        '    }\n'
        '}\n'
    )
    snapshot = _analyze(parser, 'file:///expr_ternary_domains.tcl', source)

    bg_opt_resolutions = [
        resolution
        for resolution in snapshot.analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'bg_opt'
    ]
    assert len(bg_opt_resolutions) == 1
    assert bg_opt_resolutions[0].uncertainty.state == 'resolved'

    hover_by_offset = {
        hover.span.start.offset: hover.contents for hover in snapshot.analysis.hovers
    }
    binding_offset = source.index('bg_opt')
    assert hover_by_offset[binding_offset] == 'set bg_opt: "a" | "b"'
    bg_opt_offset = source.index('$bg_opt')
    assert hover_by_offset[bg_opt_offset] == 'set bg_opt: "a" | "b"'


def test_analysis_narrows_expr_ternary_assignment_domains_from_exact_conditions(
    parser: Parser,
) -> None:
    source = (
        'proc run {} {\n'
        '    set bg 1\n'
        '    set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'
        '    puts $bg_opt\n'
        '}\n'
    )
    snapshot = _analyze(parser, 'file:///expr_ternary_exact.tcl', source)

    hover_by_offset = {
        hover.span.start.offset: hover.contents for hover in snapshot.analysis.hovers
    }
    binding_offset = source.index('bg_opt')
    assert hover_by_offset[binding_offset] == 'set bg_opt: "a"'
    bg_opt_offset = source.index('$bg_opt')
    assert hover_by_offset[bg_opt_offset] == 'set bg_opt: "a"'


def test_analysis_tracks_dict_for_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///dict_for.tcl',
        'proc helper {} {return ok}\n'
        'proc run {pairs} {\n'
        '    dict for {key value} $pairs {\n'
        '        helper\n'
        '        puts $key\n'
        '        puts $value\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['key'] == 'foreach'
    assert bindings_by_name['value'] == 'foreach'

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'key', 'value', 'pairs'}
    }
    assert {name for name, _ in variable_resolutions} == {'key', 'value', 'pairs'}
    assert set(variable_resolutions.values()) == {'resolved'}
    assert analysis.diagnostics == ()


def test_analysis_resolves_references_inside_braced_if_conditions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///if_condition.tcl',
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {$flag && [helper]} {\n'
        '        return ok\n'
        '    } elseif {[helper]} then {\n'
        '        return alt\n'
        '    }\n'
        '}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    flag_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'flag'
    ]
    assert len(flag_references) == 1
    assert flag_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_tracks_nested_if_conditions_inside_command_substitutions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///nested_if_condition.tcl',
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {[if {$flag} {helper}]} {\n'
        '        return ok\n'
        '    }\n'
        '}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    flag_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'flag'
    ]
    assert len(flag_references) == 1
    assert flag_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_extractor_does_not_duplicate_variable_references_in_command_substitutions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)

    parse_result = parser.parse_document(
        'file:///command_substitution_refs.tcl',
        'puts [foo $x [bar $y]]\n',
    )
    facts = extractor.extract(parse_result)

    assert [
        (reference.name, reference.span.start.offset, reference.span.end.offset)
        for reference in facts.variable_references
    ] == [
        ('x', 10, 12),
        ('y', 18, 20),
    ]


def test_analysis_tracks_static_if_bodies_for_metadata_guards() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///meta_file.tcl',
        'if {[llength [info commands meta]] == 0} {\n'
        '    proc meta {args} {}\n'
        '}\n'
        '# Builtin metadata entry.\n'
        'meta command after {ms}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert [proc.qualified_name for proc in facts.procedures] == ['::meta']
    assert analysis.diagnostics == ()
