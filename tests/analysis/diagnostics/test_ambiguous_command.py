from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_ambiguous_imported_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///ambiguous_command.tcl',
        'namespace eval one { proc greet {} {return one} }\n'
        'namespace eval two { proc greet {} {return two} }\n'
        'namespace eval app {\n'
        '    namespace import ::one::*\n'
        '    namespace import ::two::*\n'
        '    greet\n'
        '}\n',
    )
    analysis = snapshot.analysis

    greet_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'greet'
    )
    assert greet_resolution.uncertainty.state == 'ambiguous'

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['ambiguous-command']
    diagnostic = analysis.diagnostics[0]
    assert diagnostic.message == 'Command `greet` resolves to multiple procedures.'
    assert diagnostic.span.start.line == 5
