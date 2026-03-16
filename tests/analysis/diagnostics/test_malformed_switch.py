from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_odd_switch_branch_words(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_switch_words.tcl',
        'switch -- $kind foo {set result 1} bar\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-switch']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `switch` command; branches require pattern/body pairs.'
    )


def test_analysis_reports_odd_switch_branch_list(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_switch_list.tcl',
        'switch -- $kind {foo {set result 1} bar}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-switch']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `switch` command; branch lists require pattern/body pairs.'
    )


def test_analysis_reports_unknown_switch_option(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_switch_option.tcl',
        'switch -bogus $kind {foo {set result 1}}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-switch']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `switch` command; unknown option `-bogus`.'
    )
