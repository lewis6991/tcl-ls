from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_prefers_last_same_file_proc_definition(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///broken.tcl',
        'proc greet {} {puts $name}\nmissing_command\nproc greet {} {return ok}\ngreet\n',
    )
    analysis = snapshot.analysis

    diagnostic_codes = [diagnostic.code for diagnostic in analysis.diagnostics]
    assert 'unresolved-command' in diagnostic_codes
    assert 'unresolved-variable' in diagnostic_codes
    assert 'duplicate-proc' not in diagnostic_codes
    assert 'ambiguous-command' not in diagnostic_codes

    greet_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'greet'
    )
    assert greet_resolution.uncertainty.state == 'resolved'
