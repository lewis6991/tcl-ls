from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_unknown_builtin_option(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///regexp_option.tcl', 'regexp -bogus pat text\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['unknown-option']
    diagnostic = analysis.diagnostics[0]
    assert diagnostic.message == 'Unknown option `-bogus` for command `regexp`.'
    assert diagnostic.span.start.character == 7


def test_analysis_respects_option_stop_marker(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///return_stop.tcl', 'return -- -code error\n')
    assert snapshot.analysis.diagnostics == ()
