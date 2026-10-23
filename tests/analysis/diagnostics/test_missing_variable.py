from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.parser import Parser

from ..support import analyze_document, analyze_path


@pytest.mark.parametrize('command', ['incr count', 'append count text', 'lappend count item'])
def test_creating_a_local_variable_reports_a_hint(parser: Parser, command: str) -> None:
    source = f'proc example {{}} {{{command}; puts $count}}'
    diagnostics = analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics

    assert [(d.code, d.severity, d.message) for d in diagnostics] == [
        ('missing-variable', 'hint', 'Variable is first created here.')
    ]
    assert source[diagnostics[0].span.start.offset : diagnostics[0].span.end.offset] == 'count'


@pytest.mark.parametrize(
    'source',
    [
        'proc example {count} {incr count}',
        'proc example {{count 0}} {incr count}',
        'proc example {} {set count [read stdin]; incr count}',
        'proc example {} {incr count [set count 0]}',
        'proc example {} {append count [set count text]}',
        'proc example {} {catch {error failed} count; append count text}',
        'proc example {} {foreach count {1 2} {incr count}}',
    ],
)
def test_an_earlier_binding_prevents_a_creation_hint(parser: Parser, source: str) -> None:
    assert analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics == ()


def test_the_current_and_later_bindings_do_not_hide_the_first_creation(parser: Parser) -> None:
    source = 'proc example {} {incr count; incr count; set count 0; incr count}'
    diagnostics = analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics

    assert [(d.code, d.span.start.offset) for d in diagnostics] == [
        ('missing-variable', source.index('count'))
    ]


@pytest.mark.parametrize(
    ('body', 'hints'),
    [
        ('set count 0; unset count; incr count', 1),
        ('unset -nocomplain count; incr count', 1),
        ('if {$flag} {set count 0}; incr count', 0),
        ('if {$flag} {set count 0} else {set count 1}; incr count', 0),
        ('if {$flag} {unset -nocomplain count}; incr count', 1),
        ('set count 0; if {$flag} {unset count}; incr count', 0),
        ('if {$flag} {set count 0; return}; incr count', 1),
        ('if {$flag} {eval $script}; incr count', 0),
        ('if {[info exists count]} {incr count}', 0),
        ('set count 0; if {![info exists count]} {incr count}', 0),
        ('if {![info exists count]} {set count 0}; incr count', 0),
        ('if {[info exists count]} {} else {incr count}', 1),
        ('if {[info exists ::count] && $flag} {incr ::count}', 0),
        ('while {$flag} {set count 0}; incr count', 0),
        ('return; incr count', 0),
        ('set count(first) 1; unset count(first); incr count(second)', 0),
        (
            'if {$flag} {set target count} else {set target other}; unset -nocomplain $target; incr count',
            0,
        ),
    ],
)
def test_creation_hints_follow_unset_and_control_flow(
    parser: Parser, body: str, hints: int
) -> None:
    source = f'proc example {{flag script}} {{{body}}}'
    diagnostics = analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics

    assert len([d for d in diagnostics if d.code == 'missing-variable']) == hints


@pytest.mark.parametrize(
    'source',
    [
        'incr count',
        'namespace eval example {incr count}',
        'proc example {} {global count; incr count}',
        'proc example {} {variable count; incr count}',
        'proc example {} {upvar 1 count count; incr count}',
        'proc example {script} {eval $script; incr count}',
        'proc example {filename} {source $filename; incr count}',
        'proc example {script} {uplevel 0 $script; incr count}',
        'proc example {command} {$command; incr count}',
        'proc init {} {upvar 1 count count; set count 0}; proc example {} {init; incr count}',
        'proc incr {name} {}; proc example {} {incr count}',
    ],
)
def test_unknown_or_replaced_commands_do_not_produce_creation_hints(
    parser: Parser, source: str
) -> None:
    diagnostics = analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics

    assert not [d for d in diagnostics if d.code == 'missing-variable']


@pytest.mark.parametrize(
    'source',
    [
        'unset -nocomplain ::count; incr ::count',
        'namespace eval example {unset -nocomplain count; incr count}',
        'proc example {} {global count; unset -nocomplain count; incr count}',
    ],
)
def test_explicit_unset_can_establish_that_a_global_is_missing(parser: Parser, source: str) -> None:
    diagnostics = analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics

    assert len([d for d in diagnostics if d.code == 'missing-variable']) == 1


def test_custom_metadata_controls_the_message_and_severity(parser: Parser, tmp_path: Path) -> None:
    metadata = tmp_path / 'custom.meta.tcl'
    metadata.write_text("""
meta module Tcl {
meta command ensure {name} {
    bind 1 set
    ref 1 {if-missing {information "Check the initial value."}}
}
meta command inspect {names} {
    ref list 1 {if-missing {hint "Not yet set."}}
}
meta command read_name {name} {ref 1}
}
""")
    source = tmp_path / 'example.tcl'
    source.write_text("""
proc example {parameter} {
    ensure count
    ensure count
    inspect {count parameter other}
    read_name missing
}
""")
    _, analysis = analyze_path(parser, source, metadata_paths=(metadata,))

    assert [(d.code, d.severity, d.message) for d in analysis.diagnostics] == [
        ('missing-variable', 'information', 'Check the initial value.'),
        ('missing-variable', 'hint', 'Not yet set.'),
        ('unresolved-variable', 'warning', 'Unresolved variable `missing`.'),
    ]
    assert [
        source.read_text()[d.span.start.offset : d.span.end.offset] for d in analysis.diagnostics
    ] == ['count', 'other', 'missing']


@pytest.mark.parametrize(
    'body',
    [
        'proc example {} {tools::ensure count}',
        'proc example {} {::tools::ensure count}',
        'namespace eval tools {proc example {} {ensure count}}',
        'namespace import tools::ensure; proc example {} {ensure count}',
        'proc example {} {script {ensure count}}',
    ],
)
def test_missing_checks_follow_the_resolved_metadata_command(
    parser: Parser, tmp_path: Path, body: str
) -> None:
    metadata = tmp_path / 'custom.meta.tcl'
    metadata.write_text("""
meta module Tcl {
    meta command tools::ensure {name} {
        ref 1 {if-missing {hint "First use."}}
        bind 1 set
    }
    meta command script {body} {enter tool-script body 1}
    meta language tool-script {
        extends tcl
        command ensure {name} {
            ref 1 {if-missing {hint "First use."}}
            bind 1 set
        }
    }
}
""")
    source = tmp_path / 'example.tcl'
    source.write_text(body)
    _, analysis = analyze_path(parser, source, metadata_paths=(metadata,))

    assert [(d.code, d.severity, d.message) for d in analysis.diagnostics] == [
        ('missing-variable', 'hint', 'First use.')
    ]


@pytest.mark.parametrize('selector', ['1', 'list 1', '1..last step 2', 'after-options list 2..'])
@pytest.mark.parametrize('severity', ['hint', 'information'])
def test_missing_variable_blocks_are_valid_when_editing_metadata(
    parser: Parser, selector: str, severity: str
) -> None:
    source = (
        'meta command ensure {args} {\n'
        f'    ref {selector} {{if-missing {{{severity} "Variable is missing."}}}}\n'
        '}\n'
    )
    snapshot = analyze_document(parser, 'file:///example.meta.tcl', source)

    assert snapshot.analysis.diagnostics == ()
