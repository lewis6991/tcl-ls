from __future__ import annotations

import pytest

from tcl_lsp.parser import Parser

from ..support import analyze_document


@pytest.mark.parametrize(
    'expression',
    [
        '"42" + 1',
        '"2.5" * 2',
        '"0x10" + 1',
        '"0b10" << 1',
        '"0o10" % 3',
        '99999999999999999999999999999999999999999 + 1',
        '[list 42] + 1',
        '1e+2 + 1',
        '"1_000" + 1',
        '"0d12" + 1',
        '"010" + 1',
        '2 && yes',
        '"tr" || "of"',
        '"text" eq "other"',
        '"text" == "other"',
        '"text" < 42',
        '"text" in {some text}',
        '0 && ("bad" + 1)',
        '1 || ("bad" + 1)',
        '1 ? 42 : ("bad" + 1)',
        '0 ? ("bad" + 1) : 42',
    ],
)
def test_valid_tcl_interpretations_are_accepted(parser: Parser, expression: str) -> None:
    result = analyze_document(parser, 'file:///values.tcl', f'expr {{{expression}}}\n')
    assert result.analysis.diagnostics == ()


@pytest.mark.parametrize(
    ('expression', 'expected'),
    [
        ('"auto" + 1', 'a number'),
        ('true + 1', 'a number'),
        ('[list bad] + 1', 'a number'),
        ('[list] + 1', 'a number'),
        ('2.5 % 2', 'an integer'),
        ('~"text"', 'an integer'),
        ('2.5 << 1', 'an integer'),
        ('!"auto"', 'a boolean or number'),
        ('"auto" && 1', 'a boolean or number'),
        ('" true " && 1', 'a boolean or number'),
        ('"auto" ? 1 : 0', 'a boolean or number'),
        ('"a" in "\\{"', None),
    ],
)
def test_invalid_operands_report_the_required_interpretation(
    parser: Parser, expression: str, expected: str | None
) -> None:
    result = analyze_document(parser, 'file:///values.tcl', f'expr {{{expression}}}\n')
    diagnostics = result.analysis.diagnostics
    if expected is None:
        # Escapes that this parser does not decode remain unproved.
        assert diagnostics == ()
        return
    assert [(d.code, d.severity) for d in diagnostics] == [('invalid-expr-operand', 'error')]
    assert expected in diagnostics[0].message


def test_closed_union_reports_a_possible_bad_operand(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @alias Count integer|"auto"\n'
        '# @param count Count\n'
        'proc next_count {count} {return [expr {$count + 1}]}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-expr-operand', 'warning')
    ]
    assert '"auto"' in result.analysis.diagnostics[0].message


@pytest.mark.parametrize('annotation', ['', '# @param count string\n', '# @param count integer\n'])
def test_unrestricted_strings_and_unknown_inputs_do_not_warn(
    parser: Parser, annotation: str
) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        annotation + 'proc next_count {count} {return [expr {$count + 1}]}\n',
    )
    assert result.analysis.diagnostics == ()


@pytest.mark.parametrize(
    'body',
    [
        'if {$count ne "auto"} {expr {$count + 1}}',
        'if {$count eq "auto"} {return 0}; expr {$count + 1}',
        'if {$count eq "auto"} {error "no count"}; expr {$count + 1}',
        'if {![string is entier -strict $count]} {error "no count"}; expr {$count + 1}',
        'expr {$count eq "auto" ? 0 : $count + 1}',
        'expr {$count ne "auto" && $count + 1}',
        'expr {$count eq "auto" || $count + 1}',
    ],
)
def test_guards_remove_the_bad_alternative(parser: Parser, body: str) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count integer|"auto"\n' + f'proc next_count {{count}} {{{body}}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_false_branch_of_validation_retains_the_bad_alternative(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count integer|"auto"\n'
        'proc next_count {count} {\n'
        '    if {[string is entier -strict $count]} {return 0}\n'
        '    expr {$count + 1}\n'
        '}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-expr-operand', 'warning')
    ]


@pytest.mark.parametrize('write', ['set count [read stdin]', 'append count x', 'eval $script'])
def test_writes_and_unknown_effects_clear_constraints(parser: Parser, write: str) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count "auto"\n'
        f'proc next_count {{count script}} {{{write}; expr {{$count + 1}}}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_assignment_contract_does_not_hide_the_actual_value(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'proc next_count {} {\n    # @type integer\n    set count auto\n    expr {$count + 1}\n}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-value', 'error'),
        ('invalid-expr-operand', 'error'),
    ]


@pytest.mark.parametrize('value', ['42', '0x10', '[list 42]'])
def test_numeric_strings_satisfy_an_integer_contract(parser: Parser, value: str) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        f'# @type integer\nset count {value}\nexpr {{$count + 1}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_branch_join_retains_a_known_bad_alternative(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count integer\n'
        'proc next_count {count flag} {\n'
        '    if {$flag} {set count auto}\n'
        '    expr {$count + 1}\n'
        '}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-expr-operand', 'warning')
    ]


def test_expression_text_and_operand_data_are_distinct(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'set formula {1 + 2}\nexpr $formula\nexpr {$formula}\nexpr {$formula + 1}\n',
    )
    diagnostics = result.analysis.diagnostics
    assert [(d.code, d.span.start.line) for d in diagnostics] == [('invalid-expr-operand', 3)]


def test_numeric_equality_preserves_the_original_spelling(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'proc use {} {\n    set count 0x10\n    if {$count == 16} {puts $count}\n}\n',
    )
    assert result.facts.variable_references[-1].exact_values == ('0x10',)
    assert result.analysis.diagnostics == ()


def test_braced_expression_atom_does_not_substitute_a_variable(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'set count 42\nexpr {{$count} + 1}\n',
    )
    assert [d.code for d in result.analysis.diagnostics] == ['invalid-expr-operand']


def test_unknown_substitution_clears_stale_operand_information(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'proc use {} {set count auto; expr {[set count 42] + $count}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_conditions_use_expression_truth_conversion(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'if {"auto"} {puts yes}\n',
    )
    assert [d.code for d in result.analysis.diagnostics] == ['invalid-expr-operand']


def test_shadowed_expr_command_is_not_checked_as_a_builtin(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'proc expr {value} {return $value}\nexpr {"auto" + 1}\n',
    )
    assert result.analysis.diagnostics == ()


@pytest.mark.parametrize('value', ['{1 2 3}', '{1 auto 3}'])
def test_list_contract_checks_elements(parser: Parser, value: str) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        f'# @type integer[]\nset counts {value}\n',
    )
    expected = ['invalid-value'] if 'auto' in value else []
    assert [d.code for d in result.analysis.diagnostics] == expected


@pytest.mark.parametrize('expression', ['0 && (1 +)', '1 || auto', '1 ? 42 : (1 +)'])
def test_short_circuiting_does_not_hide_invalid_syntax(parser: Parser, expression: str) -> None:
    result = analyze_document(parser, 'file:///values.tcl', f'expr {{{expression}}}\n')
    assert [d.code for d in result.analysis.diagnostics] == ['invalid-expr']


def test_unmodelled_array_expression_is_not_a_syntax_error(parser: Parser) -> None:
    result = analyze_document(parser, 'file:///values.tcl', 'expr {$values(key) + 1}\n')
    assert result.analysis.diagnostics == ()


def test_numeric_escape_does_not_supply_incorrect_literal_evidence(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @type integer\nset count "\\x34\\x32"\nexpr {$count + 1}\n',
    )
    assert result.analysis.diagnostics == ()


def test_guard_filters_a_finite_literal_domain(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count "42"|"auto"\n'
        'proc use {count} {if {[string is entier -strict $count]} {expr {$count + 1}}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_unknown_ternary_branch_is_not_discarded_from_value_flow(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'proc use {flag unknown} {\n'
        '    set count [expr {$flag ? $unknown : "auto"}]\n'
        '    expr {$count + 1}\n'
        '}\n',
    )
    assert result.analysis.diagnostics == ()


def test_invalid_list_membership_reports_the_right_operand(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'set items "{"\nexpr {"item" in $items}\n',
    )
    assert [d.code for d in result.analysis.diagnostics] == ['invalid-expr-operand']
    assert 'a valid Tcl list' in result.analysis.diagnostics[0].message


def test_list_values_keep_their_string_interpretation_after_assignment(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'set count [list bad]\nexpr {$count + 1}\n',
    )
    assert [d.code for d in result.analysis.diagnostics] == ['invalid-expr-operand']


def test_escaped_list_elements_do_not_supply_incorrect_numeric_evidence(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        'foreach count {\\x34} {expr {$count + 1}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_assignment_contract_reports_a_possible_invalid_value(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param choice 42|"auto"\n'
        'proc use {choice} {\n'
        '    # @type integer\n'
        '    set count $choice\n'
        '    expr {$count + 1}\n'
        '}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-value', 'warning'),
        ('invalid-expr-operand', 'warning'),
    ]


def test_return_with_options_does_not_prove_the_guard_exits(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count integer|"auto"\n'
        'proc use {count} {\n'
        '    if {$count eq "auto"} {return -level 0}\n'
        '    expr {$count + 1}\n'
        '}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-expr-operand', 'warning'),
    ]


@pytest.mark.parametrize('expression', ['[set count 42]', '[eval $script]'])
def test_expression_substitutions_invalidate_later_variable_values(
    parser: Parser, expression: str
) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        f'proc use {{script}} {{set count auto; expr {{{expression}}}; expr {{$count + 1}}}}\n',
    )
    assert result.analysis.diagnostics == ()


def test_readonly_substitution_preserves_other_value_constraints(parser: Parser) -> None:
    result = analyze_document(
        parser,
        'file:///values.tcl',
        '# @param count integer|"auto"\n'
        'proc use {count} {expr {[llength {}]}; expr {$count + 1}}\n',
    )
    assert [(d.code, d.severity) for d in result.analysis.diagnostics] == [
        ('invalid-expr-operand', 'warning'),
    ]
