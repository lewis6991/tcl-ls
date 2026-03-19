from __future__ import annotations

from tcl_lsp.analysis.flow import (
    VariableFlowState,
    condition_branch_flow_states,
    dynamic_variable_target_names,
    exact_word_values,
    script_body_flow_state,
    state_with_set_command,
    state_with_unset_command,
    switch_branch_flow_state,
)
from tcl_lsp.parser import Parser
from tcl_lsp.parser.model import Command


def _single_command(parser: Parser, text: str) -> Command:
    parse_result = parser.parse_document('file:///flow.tcl', text)
    assert parse_result.diagnostics == ()
    assert len(parse_result.script.commands) == 1
    return parse_result.script.commands[0]


def test_variable_flow_tracks_static_set_values(parser: Parser) -> None:
    state = state_with_set_command(
        VariableFlowState.empty(),
        _single_command(parser, 'set target engines\n'),
    )

    assert state.exact_values('target') == ('engines',)


def test_variable_flow_tracks_alias_assignments_from_known_values(parser: Parser) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(state, _single_command(parser, 'set target engines\n'))
    state = state_with_set_command(state, _single_command(parser, 'set alias $target\n'))

    assert state.exact_values('alias') == ('engines',)


def test_variable_flow_clears_exact_values_when_set_rhs_is_unknown(parser: Parser) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(state, _single_command(parser, 'set target engines\n'))
    state = state_with_set_command(state, _single_command(parser, 'set target [clock seconds]\n'))

    assert state.exact_values('target') == ()


def test_variable_flow_derives_foreach_domains_from_static_list_variables(
    parser: Parser,
) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(
        state, _single_command(parser, 'set names {mode run_limit engines}\n')
    )
    command = _single_command(parser, 'foreach v $names {return $v}\n')

    body_state = script_body_flow_state(
        state,
        metadata_command_name='foreach',
        argument_words=command.words[1:],
        selected_word=command.words[-1],
    )

    assert body_state.exact_values('v') == ('mode', 'run_limit', 'engines')


def test_variable_flow_derives_multi_variable_domains_from_exact_list_values(
    parser: Parser,
) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(
        state,
        _single_command(parser, 'set pairs {mode auto run_limit 3 engines fast}\n'),
    )
    command = _single_command(parser, 'foreach {name value} $pairs {return [list $name $value]}\n')

    body_state = script_body_flow_state(
        state,
        metadata_command_name='foreach',
        argument_words=command.words[1:],
        selected_word=command.words[-1],
    )

    assert body_state.exact_values('name') == ('mode', 'run_limit', 'engines')
    assert body_state.exact_values('value') == ('auto', '3', 'fast')


def test_variable_flow_resolves_dynamic_target_names_from_exact_domains(parser: Parser) -> None:
    state = VariableFlowState({'slot': ('mode', 'mode', 'bad name', 'engines')})
    command = _single_command(parser, 'set $slot 1\n')

    assert dynamic_variable_target_names(command.words[1], state) == ('mode', 'engines')


def test_variable_flow_resolves_exact_word_values_from_single_variable_substitutions(
    parser: Parser,
) -> None:
    state = VariableFlowState({'slot': ('engines',)})
    command = _single_command(parser, 'set alias $slot\n')

    assert exact_word_values(command.words[2], state) == ('engines',)


def test_variable_flow_unset_clears_dynamic_target_domains(parser: Parser) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(state, _single_command(parser, 'set slot engines\n'))
    state = state_with_set_command(state, _single_command(parser, 'set engines ready\n'))
    state = state_with_unset_command(state, _single_command(parser, 'unset $slot\n'))

    assert state.exact_values('slot') == ('engines',)
    assert state.exact_values('engines') == ()


def test_variable_flow_tracks_expr_ternary_result_domains(parser: Parser) -> None:
    state = state_with_set_command(
        VariableFlowState.empty(),
        _single_command(parser, 'set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'),
    )

    assert state.exact_values('bg_opt') == ('a', 'b')


def test_variable_flow_narrows_expr_ternary_to_true_branch_when_condition_is_exact(
    parser: Parser,
) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(state, _single_command(parser, 'set bg 1\n'))
    state = state_with_set_command(
        state,
        _single_command(parser, 'set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'),
    )

    assert state.exact_values('bg_opt') == ('a',)


def test_variable_flow_tracks_expr_ternary_variable_branch_values(parser: Parser) -> None:
    state = VariableFlowState.empty()
    state = state_with_set_command(state, _single_command(parser, 'set on fast\n'))
    state = state_with_set_command(state, _single_command(parser, 'set off slow\n'))
    state = state_with_set_command(
        state,
        _single_command(parser, 'set mode [expr {$flag == 1 ? $on : $off}]\n'),
    )

    assert state.exact_values('mode') == ('fast', 'slow')


def test_variable_flow_tracks_switch_command_substitution_result_domains(
    parser: Parser,
) -> None:
    state = VariableFlowState({'mode': ('direct_alpha', 'direct_beta', 'mode_1', 'mode_2')})
    state = state_with_set_command(
        state,
        _single_command(
            parser,
            'set mapped_mode [switch $mode {'
            'mode_1 {concat target_alpha} '
            'mode_2 {concat target_beta} '
            'default {concat $mode}'
            '}]\n',
        ),
    )

    assert state.exact_values('mapped_mode') == (
        'target_alpha',
        'target_beta',
        'direct_alpha',
        'direct_beta',
    )


def test_variable_flow_narrows_equality_conditions_with_known_domains() -> None:
    then_state, else_state = condition_branch_flow_states(
        VariableFlowState({'kind': ('prove', 'lint')}),
        '$kind eq "prove"',
    )

    assert then_state.exact_values('kind') == ('prove',)
    assert else_state.exact_values('kind') == ('lint',)


def test_variable_flow_narrows_inequality_conditions_with_known_domains() -> None:
    then_state, else_state = condition_branch_flow_states(
        VariableFlowState({'kind': ('prove', 'lint')}),
        '$kind ne "prove"',
    )

    assert then_state.exact_values('kind') == ('lint',)
    assert else_state.exact_values('kind') == ('prove',)


def test_variable_flow_preserves_unknown_else_branch_for_unknown_domains() -> None:
    then_state, else_state = condition_branch_flow_states(
        VariableFlowState.empty(),
        '$kind eq "prove"',
    )

    assert then_state.exact_values('kind') == ('prove',)
    assert else_state.exact_values('kind') == ()


def test_variable_flow_narrows_exact_switch_branches(parser: Parser) -> None:
    command = _single_command(parser, 'switch -- $kind {alpha {return ok} beta {return ok}}\n')

    branch_state = switch_branch_flow_state(
        VariableFlowState.empty(),
        value_word=command.words[2],
        match_mode='exact',
        nocase=False,
        patterns=('alpha', 'beta'),
    )

    assert branch_state.exact_values('kind') == ('alpha', 'beta')


def test_variable_flow_narrows_literal_regexp_switch_branches(parser: Parser) -> None:
    command = _single_command(parser, 'switch -regexp $kind {alpha {return ok} beta {return ok}}\n')

    branch_state = switch_branch_flow_state(
        VariableFlowState.empty(),
        value_word=command.words[2],
        match_mode='regexp',
        nocase=False,
        patterns=('alpha', 'beta'),
    )

    assert branch_state.exact_values('kind') == ('alpha', 'beta')


def test_variable_flow_skips_non_literal_regexp_switch_branches(parser: Parser) -> None:
    command = _single_command(parser, 'switch -regexp $kind {[ab].* {return ok}}\n')

    branch_state = switch_branch_flow_state(
        VariableFlowState.empty(),
        value_word=command.words[2],
        match_mode='regexp',
        nocase=False,
        patterns=('[ab].*',),
    )

    assert branch_state.exact_values('kind') == ()


def test_variable_flow_supports_literal_on_left_side_and_elseif_residuals() -> None:
    state = VariableFlowState({'kind': ('prove', 'lint', 'scan')})
    _, residual_state = condition_branch_flow_states(state, '"prove" eq $kind')
    then_state, else_state = condition_branch_flow_states(residual_state, '$kind == "lint"')

    assert then_state.exact_values('kind') == ('lint',)
    assert else_state.exact_values('kind') == ('scan',)


def test_variable_flow_ignores_complex_conditions() -> None:
    state = VariableFlowState({'kind': ('prove', 'lint')})
    then_state, else_state = condition_branch_flow_states(
        state,
        '$kind eq "prove" && $mode eq "fast"',
    )

    assert then_state == state
    assert else_state == state
