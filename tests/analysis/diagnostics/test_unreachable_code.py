from __future__ import annotations

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_unreachable_command_after_return(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///unreachable_return.tcl',
        'proc run {} {\n    return ok\n    set later 1\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unreachable-code']
    assert snapshot.analysis.diagnostics[0].message == 'Command is unreachable.'
    assert snapshot.analysis.diagnostics[0].severity == 'hint'
    assert snapshot.analysis.diagnostics[0].tags == ('unnecessary',)
    assert snapshot.analysis.diagnostics[0].span.start.line == 2
    assert snapshot.analysis.diagnostics[0].span.start.character == 4
    assert snapshot.analysis.diagnostics[0].span.end.character == 15


def test_analysis_reports_unreachable_if_body_for_false_static_condition(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///unreachable_false_if_branch.tcl',
        'if {0 eq 1} {\n    puts hello\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unreachable-code']
    assert snapshot.analysis.diagnostics[0].span.start.line == 1


def test_analysis_reports_unreachable_command_after_break_in_loop_body(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///unreachable_break.tcl',
        'proc run {} {\n    while {1} {\n        break\n        set later 1\n    }\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unreachable-code']
    assert snapshot.analysis.diagnostics[0].span.start.line == 3


def test_analysis_reports_unreachable_command_after_exhaustive_if_returns(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///unreachable_if.tcl',
        'proc run {} {\n'
        '    if {1} {\n'
        '        return one\n'
        '    } else {\n'
        '        return two\n'
        '    }\n'
        '    set later 1\n'
        '}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'unreachable-code',
        'unreachable-code',
    ]
    assert [diagnostic.span.start.line for diagnostic in snapshot.analysis.diagnostics] == [4, 6]


def test_analysis_reports_unreachable_command_after_exhaustive_switch_returns(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///unreachable_switch.tcl',
        'proc run {mode} {\n'
        '    switch -- $mode {\n'
        '        a {return one}\n'
        '        default {return two}\n'
        '    }\n'
        '    set later 1\n'
        '}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == ['unreachable-code']
    assert snapshot.analysis.diagnostics[0].span.start.line == 5


def test_analysis_does_not_report_unreachable_after_catch(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///reachable_after_catch.tcl',
        'proc run {} {\n    catch { return ok }\n    set later 1\n}\n',
    )

    assert snapshot.analysis.diagnostics == ()


def test_analysis_reachability_works_without_parse_result(parser: Parser) -> None:
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///unreachable_without_parse_result.tcl',
        'proc run {} {\n    return ok\n    set later 1\n}\n',
    )
    facts = extractor.extract(parse_result, include_parse_result=False)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert facts.parse_result is None
    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['unreachable-code']
