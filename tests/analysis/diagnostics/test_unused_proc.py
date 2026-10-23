from __future__ import annotations

import pytest

from tcl_lsp.common import Diagnostic
from tcl_lsp.parser import Parser

from ..support import analyze_document, analyze_workspace


def _unused(parser: Parser, source: str) -> tuple[Diagnostic, ...]:
    return tuple(
        d
        for d in analyze_document(parser, 'file:///example.tcl', source).analysis.diagnostics
        if d.code == 'unused-proc'
    )


def test_only_private_procedures_get_unused_hints(parser: Parser) -> None:
    source = 'namespace eval app {proc _unused {} {}; proc __also_unused {} {}; proc public {} {}}'
    diagnostics = _unused(parser, source)

    assert [d.message for d in diagnostics] == [
        'Procedure `::app::_unused` is unused.',
        'Procedure `::app::__also_unused` is unused.',
    ]
    assert [source[d.span.start.offset : d.span.end.offset] for d in diagnostics] == [
        '_unused',
        '__also_unused',
    ]
    assert all(d.severity == 'hint' and d.tags == ('unnecessary',) for d in diagnostics)


def test_private_procedures_in_different_namespaces_have_separate_uses(parser: Parser) -> None:
    source = (
        'namespace eval app {proc _helper {} {}; proc run {} {_helper}}\n'
        'namespace eval other {proc _helper {} {}}\n'
    )
    assert [d.message for d in _unused(parser, source)] == [
        'Procedure `::other::_helper` is unused.'
    ]


@pytest.mark.parametrize(
    'use',
    [
        'proc run {} {_helper}',
        '::app::_helper',
        'after idle ::app::_helper',
        'after idle {::app::_helper argument}',
        'set callback [list ::app::_helper argument]',
        'namespace eval ::consumer {namespace import ::app::_helper; _helper}',
        'rename ::app::_helper exported; exported',
    ],
)
def test_calls_and_literal_callback_names_count_as_uses(parser: Parser, use: str) -> None:
    source = (
        'namespace eval app {namespace export _helper; '
        f'proc _helper {{args}} {{puts $args}}; {use}}}'
    )
    assert _unused(parser, source) == ()


def test_self_recursion_does_not_use_an_otherwise_unused_procedure(parser: Parser) -> None:
    assert [d.message for d in _unused(parser, 'proc _helper {} {_helper}')] == [
        'Procedure `::_helper` is unused.'
    ]


def test_a_call_in_another_indexed_file_counts_as_a_use(parser: Parser) -> None:
    result = analyze_workspace(
        parser,
        [
            ('file:///helper.tcl', 'namespace eval app {proc _helper {} {}}'),
            ('file:///main.tcl', '::app::_helper'),
        ],
        'file:///helper.tcl',
    )
    assert not any(d.code == 'unused-proc' for d in result.analysis.diagnostics)


def test_dynamic_calls_do_not_hide_every_unused_private_procedure(parser: Parser) -> None:
    assert [d.message for d in _unused(parser, 'proc _unused {} {}; $::command')] == [
        'Procedure `::_unused` is unused.'
    ]


def test_a_procedure_in_unreachable_code_does_not_get_a_second_hint(parser: Parser) -> None:
    assert _unused(parser, 'proc run {} {return; proc _unused {} {}}') == ()
