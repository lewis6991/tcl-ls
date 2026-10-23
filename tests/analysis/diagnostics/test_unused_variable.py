from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.common import Diagnostic
from tcl_lsp.parser import Parser

from ..support import analyze_document, analyze_path


def _unused(parser: Parser, source: str) -> tuple[Diagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in analyze_document(
            parser, 'file:///example.tcl', source
        ).analysis.diagnostics
        if diagnostic.code == 'unused-variable'
    )


def test_unused_locals_and_parameters_have_one_hint_at_the_first_binding(parser: Parser) -> None:
    source = (
        'proc example {argument {optional default} args} {\n'
        '    set unused 1\n'
        '    set unused 2\n'
        '    set used 3\n'
        '    return $used\n'
        '}\n'
    )
    diagnostics = _unused(parser, source)

    assert [d.message for d in diagnostics] == [
        'Variable `argument` is unused.',
        'Variable `optional` is unused.',
        'Variable `args` is unused.',
        'Variable `unused` is unused.',
    ]
    assert [source[d.span.start.offset : d.span.end.offset] for d in diagnostics] == [
        'argument',
        'optional',
        'args',
        'unused',
    ]
    assert diagnostics[-1].span.start.line == 1
    assert all(d.severity == 'hint' and d.tags == ('unnecessary',) for d in diagnostics)


@pytest.mark.parametrize('declaration', ['variable', 'global', 'upvar 1 remote'])
def test_an_unused_local_link_has_a_hint(parser: Parser, declaration: str) -> None:
    source = f'proc example {{}} {{{declaration} unused}}'
    diagnostics = _unused(parser, source)

    assert [d.message for d in diagnostics] == ['Variable `unused` is unused.']
    assert source[diagnostics[0].span.start.offset : diagnostics[0].span.end.offset] == 'unused'


def test_namespace_uses_do_not_use_another_procedures_local_link(parser: Parser) -> None:
    source = (
        'namespace eval tool {\n'
        '    variable version 1\n'
        '    proc init {} {variable version}\n'
        '    proc get {} {variable version; return $version}\n'
        '}\n'
    )
    assert [d.span.start.line for d in _unused(parser, source)] == [2]


@pytest.mark.parametrize(
    'body',
    [
        'variable value 1',
        'variable ::tool::value 1',
        'variable value; set value 1',
        'global value; set value 1',
        'upvar 1 remote value; set value 1',
        'set value 1; upvar 0 value alias; puts $alias',
        'set value 1; set value',
        'array set value {key 1}; puts $value(key)',
        'set value(key) 1; array get value',
        'set value 1; if {[info exists value]} {return ok}',
        'set value 1; unset value',
        'set value 1; incr value',
        'set value 1; expr {$value + 1}',
        'set value 1; return [expr {[list $value] + 1}]',
        'set value 1; if {[read stdin]} {puts $value}',
        'foreach value {1 2} {puts $value}',
        'set _ignored 1',
    ],
)
def test_reads_side_effects_and_intentional_names_are_not_unused(parser: Parser, body: str) -> None:
    assert _unused(parser, f'proc example {{}} {{{body}}}') == ()


@pytest.mark.parametrize(
    'body',
    [
        'set value 1; eval {puts $value}',
        'set value 1; uplevel 0 {puts $value}',
        'set value 1; subst {$value}',
        'set value 1; source script.tcl',
        'set value 1; info locals',
        'set value 1; info lo',
        'set value 1; info vars v*',
        'set value 1; set [read stdin]',
        'set value 1; set [read stdin] 2',
        'set value 1; incr [read stdin]',
        'set value 1; expr [read stdin]',
        'set value 1; if [read stdin] {return ok}',
        'set value 1; $command',
        'set value 1; helper [read stdin]',
        'set value 1; helper {*}[read stdin]',
        'set value 1; helper value',
        'set value 1; trace add variable value write callback',
    ],
)
def test_indirect_uses_prevent_false_hints(parser: Parser, body: str) -> None:
    assert _unused(parser, f'proc example {{}} {{{body}}}') == ()


def test_nested_procedures_have_separate_local_variables(parser: Parser) -> None:
    source = 'proc outer {value} {proc inner {value} {puts $value}}'
    diagnostics = _unused(parser, source)

    assert len(diagnostics) == 1
    assert diagnostics[0].span.start.offset == source.index('value')


@pytest.mark.parametrize('text', ['literal $value', '[literal]', 'literal; text', 'literal\ntext'])
def test_literal_command_arguments_do_not_hide_unused_variables(parser: Parser, text: str) -> None:
    source = (
        'proc log {message} {puts $message}\n'
        f'proc example {{}} {{set value 1; log {{{text}}}}}\n'
    )
    assert [d.message for d in _unused(parser, source)] == ['Variable `value` is unused.']


def test_metadata_script_bodies_record_uses_without_hiding_unused_variables(
    parser: Parser, tmp_path: Path
) -> None:
    metadata = tmp_path / 'wrapper.meta.tcl'
    metadata.write_text(
        'meta module Tcl {meta command with_interrupts {code} {enter tcl body 1}}\n'
    )
    source = (
        'proc with_interrupts {code} {tailcall try $code}\n'
        'proc wait_for_engines {} {\n'
        '    set last_report_time 0\n'
        '    set processed_cexs {}\n'
        '    set progress 0\n'
        '    set unused 0\n'
        '    with_interrupts {\n'
        '        puts $last_report_time\n'
        '        puts $processed_cexs\n'
        '        puts $progress\n'
        '    }\n'
        '}\n'
    )
    path = tmp_path / 'example.tcl'
    path.write_text(source)
    _, analysis = analyze_path(parser, path, metadata_paths=(metadata,))

    assert [d.message for d in analysis.diagnostics] == ['Variable `unused` is unused.']


def test_global_variables_and_underscore_parameters_are_excluded(parser: Parser) -> None:
    assert _unused(parser, 'set value 1; proc example {_event args} {puts $args}') == ()


def test_unreachable_bindings_do_not_get_another_unused_hint(parser: Parser) -> None:
    assert _unused(parser, 'proc example {} {return; set value 1}') == ()


def test_metadata_procedures_and_references_are_supported(parser: Parser, tmp_path: Path) -> None:
    metadata = tmp_path / 'custom.meta.tcl'
    metadata.write_text(
        'meta module Tcl {\n'
        'meta command define {name params body} {\n'
        '    procedure {name {select 1}; params {select 2}; body {select 3}}\n'
        '}\n'
        'meta command consume {name} {ref 1}\n'
        'meta command run {script} {enter tcl body 1}\n'
        '}\n'
    )
    source = tmp_path / 'example.tcl'
    source.write_text(
        'define example {unused} {variable version; set value 1; consume value}\n'
        'define dynamic {} {set value 1; consume [read stdin]}\n'
        'define script {} {set value 1; run [read stdin]}\n'
    )
    _, analysis = analyze_path(parser, source, metadata_paths=(metadata,))

    assert [d.message for d in analysis.diagnostics if d.code == 'unused-variable'] == [
        'Variable `unused` is unused.',
        'Variable `version` is unused.',
    ]
