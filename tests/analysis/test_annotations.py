from __future__ import annotations

import pytest

from tcl_lsp.analysis.types import (
    GenericType,
    ListType,
    LiteralType,
    NamedType,
    RecordType,
    TupleType,
    UnionType,
)
from tcl_lsp.parser import Parser
from tests.analysis.support import analyze_document, analyze_workspace


def test_aliases_supply_structured_parameter_and_return_facts(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """namespace eval properties {
    # @param actual Snapshot State before conversion.
    # @return [Snapshot, string[]] Updated state and changed names.
    proc update {actual} {return [list $actual {}]}

    # Aliases also apply to declarations earlier in this namespace.
    # @alias State "enabled"|"disabled"
    # @alias Snapshot dict<string, {state: State, names: string[]}>
}
""",
    )
    proc = snapshot.facts.procedures[0]
    parameter = proc.parameters[0]
    assert parameter.documentation == 'State before conversion.'
    assert parameter.type_info is not None
    assert parameter.type_info.expression.node == NamedType('Snapshot')
    record = GenericType(
        'dict',
        (
            NamedType('string'),
            RecordType(
                (
                    (
                        'state',
                        UnionType(
                            (LiteralType('enabled', 'string'), LiteralType('disabled', 'string'))
                        ),
                    ),
                    ('names', ListType(NamedType('string'))),
                )
            ),
        ),
    )
    assert parameter.type_info.resolved == record
    assert proc.return_type is not None
    assert proc.return_type.resolved == TupleType((record, ListType(NamedType('string'))))
    assert snapshot.facts.variable_bindings[0].type_info == parameter.type_info
    assert snapshot.facts.variable_references[0].type_info == parameter.type_info
    assert snapshot.facts.variable_references[0].exact_values == ()
    assert [item.annotation.tag for item in snapshot.facts.comment_annotations] == [
        'param',
        'return',
        'alias',
        'alias',
    ]
    assert snapshot.analysis.diagnostics == ()


def test_annotated_literal_domains_follow_copies_and_narrow_in_branches(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """# @alias State "enabled"|"disabled"
# @param state State
proc use {state} {
    set copy $state
    if {$copy eq "enabled"} {
        puts $copy
    } else {
        puts $copy
    }
    puts $copy
}
""",
    )
    references = [ref for ref in snapshot.facts.variable_references if ref.name == 'copy']
    assert [ref.exact_values for ref in references] == [
        ('enabled', 'disabled'),
        ('enabled',),
        ('disabled',),
        ('enabled', 'disabled'),
    ]
    assert all(ref.type_info and ref.type_info.expression.text == 'State' for ref in references)
    hovers = {hover.span.start.line: hover.contents for hover in snapshot.analysis.hovers}
    assert hovers[5] == 'set copy: State = "enabled"'
    assert hovers[7] == 'set copy: State = "disabled"'
    assert hovers[9] == 'set copy: State'
    assert snapshot.analysis.diagnostics == ()


def test_type_comments_annotate_assignments_and_direct_copies(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """proc use {} {
    # @type dict<string, integer>
    set counts [read stdin]
    set copy $counts
    puts $copy
    set copy replacement
    puts $copy
    puts $counts
}
""",
    )
    bindings = snapshot.facts.variable_bindings
    assert bindings[0].type_info is not None
    assert bindings[0].type_info.resolved == GenericType(
        'dict', (NamedType('string'), NamedType('integer'))
    )
    assert bindings[1].type_info == bindings[0].type_info
    assert bindings[2].type_info is None
    copies = [ref for ref in snapshot.facts.variable_references if ref.name == 'copy']
    assert copies[0].type_info == bindings[0].type_info
    assert copies[1].type_info is None
    assert copies[1].exact_values == ('replacement',)
    assert snapshot.facts.variable_references[-1].type_info == bindings[0].type_info


@pytest.mark.parametrize(
    'write',
    [
        'append value suffix',
        'incr value',
        'unset value; set value [read stdin]',
        'eval [read stdin]',
        'global value',
        'upvar 1 other value',
        'if {$condition} {set value replacement}',
    ],
)
def test_writes_and_uncertain_links_clear_annotated_flow_types(parser: Parser, write: str) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        f"""# @param value integer
proc use {{value condition}} {{
    puts $value
    {write}
    puts $value
}}
""",
    )
    references = [ref for ref in snapshot.facts.variable_references if ref.name == 'value']
    assert references[0].type_info is not None
    assert references[-1].type_info is None


@pytest.mark.parametrize('type_name', ['Cycle', 'Open', 'Missing'])
def test_recursive_or_open_types_do_not_claim_a_finite_value_domain(
    parser: Parser, type_name: str
) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        f"""# @alias Cycle Cycle|"enabled"
# @alias Open string|"enabled"
# @param state {type_name}
proc use {{state}} {{puts $state}}
""",
    )
    reference = snapshot.facts.variable_references[0]
    assert reference.type_info is not None
    assert reference.type_info.expression.text == type_name
    assert reference.exact_values == ()
    assert snapshot.analysis.diagnostics == ()


def test_type_comments_do_not_cross_blank_lines_or_create_variables(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """proc use {} {
    # @type integer

    set value [read stdin]
    puts $value
    # @type integer
    puts $missing
}
""",
    )
    assert snapshot.facts.variable_bindings[0].type_info is None
    assert [binding.name for binding in snapshot.facts.variable_bindings] == ['value']
    assert all(ref.type_info is None for ref in snapshot.facts.variable_references)
    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'unresolved-variable'
    ]


def test_literal_annotations_resolve_a_dynamic_variable_write(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """# @alias Target "result"
# @alias Target string
# @alias Target "result"
proc use {} {
    # @type Target
    set target [read stdin]
    set $target 1
    puts $result
}
""",
    )
    bindings = snapshot.facts.variable_bindings
    assert [binding.name for binding in bindings] == ['target', 'result']
    assert bindings[0].exact_values == ('result',)
    assert snapshot.facts.variable_references[-1].exact_values == ('1',)
    assert snapshot.analysis.diagnostics == ()


def test_return_types_follow_substitutions_copies_and_branch_narrowing(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """proc use {} {
    set state [read_state]
    set copy "$state"
    if {$copy eq "enabled"} {puts $copy} else {puts $copy}
    set copy replacement
    puts $copy
}
# @alias State "enabled"|"disabled"
# @return State
proc read_state {} {return enabled}
""",
    )
    references = [ref for ref in snapshot.facts.variable_references if ref.name == 'copy']
    assert [ref.exact_values for ref in references] == [
        ('enabled', 'disabled'),
        ('enabled',),
        ('disabled',),
        ('replacement',),
    ]
    assert all(ref.type_info and ref.type_info.expression.text == 'State' for ref in references[:3])
    assert references[-1].type_info is None
    assert 'set copy: State = "enabled"' in [hover.contents for hover in snapshot.analysis.hovers]
    assert snapshot.analysis.diagnostics == ()


@pytest.mark.parametrize(
    'value',
    [
        'prefix[read_state]',
        '{[read_state]}',
        '[read_state; puts done]',
        '[return early; read_state]',
    ],
)
def test_return_type_does_not_cover_concatenated_literal_or_multi_command_words(
    parser: Parser,
    value: str,
) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        '# @return integer\nproc read_state {} {return 1}\n'
        f'proc use {{}} {{set value {value}; puts $value}}\n',
    )
    reference = next(ref for ref in snapshot.facts.variable_references if ref.name == 'value')
    assert reference.type_info is None


@pytest.mark.parametrize('return_type', ['[State, integer]', 'Pair'])
def test_lassign_projects_tuple_results_and_copies(parser: Parser, return_type: str) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        f"""# @alias State "enabled"|"disabled"
# @alias Pair [State, integer]
# @return {return_type}
proc read_state {{}} {{return {{enabled 3}}}}
proc use {{}} {{
    lassign [read_state] state count missing
    puts $state
    puts $count
    puts $missing
    set pair [read_state]
    set copy $pair
    lassign $copy second_state second_count
    puts $second_state
    puts $second_count
    lassign unknown state count
    puts $state
    puts $count
}}
""",
    )
    references = snapshot.facts.variable_references
    state_refs = [ref for ref in references if ref.name in {'state', 'second_state'}]
    assert [ref.exact_values for ref in state_refs] == [
        ('enabled', 'disabled'),
        ('enabled', 'disabled'),
        (),
    ]
    assert state_refs[0].type_info == state_refs[1].type_info
    assert state_refs[-1].type_info is None
    counts = [ref for ref in references if ref.name in {'count', 'second_count'}]
    assert [ref.type_info.resolved if ref.type_info else None for ref in counts] == [
        NamedType('integer'),
        NamedType('integer'),
        None,
    ]
    missing = next(ref for ref in references if ref.name == 'missing')
    assert missing.type_info and missing.type_info.resolved == LiteralType('', 'string')
    assert missing.exact_values == ('',)
    bindings = [binding for binding in snapshot.facts.variable_bindings if binding.name == 'state']
    assert bindings[0].type_info == state_refs[0].type_info
    assert bindings[-1].type_info is None
    assert snapshot.analysis.diagnostics == ()


def test_shadowed_lassign_does_not_supply_tuple_element_types(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """proc lassign {value name} {}
proc use {} {
    # @type [integer]
    set pair {}
    set output plain
    lassign $pair output
    puts $output
}
""",
    )
    refs = [ref for ref in snapshot.facts.variable_references if ref.name == 'output']
    assert len(refs) == 1
    assert refs[0].type_info is None


def test_tuple_assignment_keeps_dynamic_targets_conservative(parser: Parser) -> None:
    snapshot = analyze_document(
        parser,
        'file:///main.tcl',
        """# @param target "left"|"right"
# @param pair [integer, string]
proc use {target pair} {
    # @type integer
    set left 1
    # @type integer
    set right 2
    lassign $pair $target fixed
    puts $left
    puts $right
    puts $fixed
}
""",
    )
    refs = {ref.name: ref for ref in snapshot.facts.variable_references}
    assert refs['left'].type_info is None
    assert refs['right'].type_info is None
    assert refs['fixed'].type_info and refs['fixed'].type_info.resolved == NamedType('string')


def test_ambiguous_procedure_calls_do_not_supply_return_types(parser: Parser) -> None:
    snapshot = analyze_workspace(
        parser,
        (
            ('file:///a.tcl', '# @return integer\nproc duplicate {} {return 1}\n'),
            ('file:///b.tcl', '# @return string\nproc duplicate {} {return text}\n'),
            ('file:///main.tcl', 'proc use {} {set value [duplicate]; puts $value}\n'),
        ),
        'file:///main.tcl',
    )
    assert snapshot.facts.variable_references[0].type_info is None
    call = next(
        item for item in snapshot.analysis.resolutions if item.reference.name == 'duplicate'
    )
    assert call.uncertainty.state == 'ambiguous'
