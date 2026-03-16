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


def test_analysis_skips_unknown_option_checks_for_return_result_strings(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///return_dash_result.tcl', 'return -1\nreturn -error\n')
    assert snapshot.analysis.diagnostics == ()


def test_analysis_skips_unknown_option_checks_for_return_option_pairs(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///return_custom_options.tcl',
        'return -bogus foo bar\nreturn -code {*}$args -bogus\n',
    )
    assert snapshot.analysis.diagnostics == ()
