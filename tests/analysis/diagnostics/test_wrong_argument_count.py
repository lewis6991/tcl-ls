from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_wrong_builtin_argument_count(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///pwd_args.tcl', 'pwd extra\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['wrong-argument-count']
    assert analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `pwd`; expected 0, got 1.'
    )


def test_analysis_reports_wrong_proc_argument_count(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///greet_args.tcl', 'proc greet {name} {}\ngreet\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['wrong-argument-count']
    assert analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `greet`; expected 1, got 0.'
    )


def test_analysis_uses_proc_default_parameters_for_argument_checks(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///greet_defaults.tcl',
        'proc greet {name {title friend}} {}\ngreet Ada Dr Extra\n',
    )
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['wrong-argument-count']
    assert analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `greet`; expected 1..2, got 3.'
    )


def test_analysis_checks_most_specific_builtin_subcommand_arguments(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///binary_encode_hex.tcl', 'binary encode hex\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['wrong-argument-count']
    assert analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `binary encode hex`; expected 1, got 0.'
    )


def test_analysis_skips_unsupported_builtin_argument_signatures(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///binary_encode.tcl', 'binary encode\n')
    assert snapshot.analysis.diagnostics == ()
