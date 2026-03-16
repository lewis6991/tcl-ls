from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_missing_elseif_body(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_if_elseif.tcl',
        'if {$flag} {puts ok} elseif {$other}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-if']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `if` command; `elseif` requires a test and body.'
    )


def test_analysis_reports_unexpected_trailing_if_keyword(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_if_trailing.tcl',
        'if {$flag} {puts ok} bogus {$other}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-if']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `if` command; expected `elseif` or `else`, got `bogus`.'
    )


def test_analysis_reports_trailing_words_after_else_body(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///malformed_if_else_trailing.tcl',
        'if {$flag} {puts ok} else {puts no} extra\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['malformed-if']
    assert snapshot.analysis.diagnostics[0].message == (
        'Malformed `if` command; trailing words after `else` body.'
    )
