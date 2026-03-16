from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_ambiguous_proc_variable_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///ambiguous_variable.tcl',
        'set shared 0\nproc run {shared} {\n    global shared\n    puts $shared\n}\n',
    )
    analysis = snapshot.analysis

    shared_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name == 'shared'
        and resolution.reference.procedure_symbol_id is not None
    ]
    assert len(shared_resolutions) == 2
    assert all(resolution.uncertainty.state == 'ambiguous' for resolution in shared_resolutions)

    ambiguous_variables = [
        diagnostic for diagnostic in analysis.diagnostics if diagnostic.code == 'ambiguous-variable'
    ]
    assert len(ambiguous_variables) == 2
    assert all(
        diagnostic.message == 'Variable `shared` resolves to multiple bindings.'
        for diagnostic in ambiguous_variables
    )
    assert [diagnostic.span.start.line for diagnostic in ambiguous_variables] == [2, 3]
