from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_missing_builtin_option_value(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///regexp_missing_value.tcl', 'regexp -start\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['missing-option-value']
    diagnostic = analysis.diagnostics[0]
    assert diagnostic.message == 'Option `-start` for command `regexp` requires a value.'
    assert diagnostic.span.start.character == 7


def test_analysis_skips_missing_option_value_checks_for_return(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///return_code_literal.tcl', 'return -code\n')
    assert snapshot.analysis.diagnostics == ()
