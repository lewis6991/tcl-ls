from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_unknown_builtin_subcommand(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///unknown_info_subcommand.tcl',
        'info gurka\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unknown-subcommand']
    assert snapshot.analysis.diagnostics[0].message == (
        'Unknown subcommand `gurka` for command `info`.'
    )


def test_analysis_reports_unknown_nested_builtin_subcommand(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///unknown_namespace_ensemble_subcommand.tcl',
        'namespace ensemble frob widget\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unknown-subcommand']
    assert snapshot.analysis.diagnostics[0].message == (
        'Unknown subcommand `frob` for command `namespace ensemble`.'
    )


def test_analysis_reports_unknown_explicit_builtin_subcommand(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///unknown_binary_decode_subcommand.tcl',
        'binary decode frob payload\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unknown-subcommand']
    assert snapshot.analysis.diagnostics[0].message == (
        'Unknown subcommand `frob` for command `binary decode`.'
    )


def test_analysis_accepts_unique_builtin_subcommand_abbreviations(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///abbreviated_info_subcommand.tcl',
        'info bod greet\n',
    )

    assert snapshot.analysis.diagnostics == ()


def test_analysis_keeps_unknown_subcommand_checks_for_stable_positions(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///unknown_info_subcommand_with_expanded_tail.tcl',
        'info gurka {*}$args\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unknown-subcommand']
    assert snapshot.analysis.diagnostics[0].message == (
        'Unknown subcommand `gurka` for command `info`.'
    )
