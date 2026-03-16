from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_workspace as _analyze_workspace


def test_analysis_reports_duplicate_procs_across_documents(parser: Parser) -> None:
    snapshot = _analyze_workspace(
        parser,
        (
            ('file:///first.tcl', 'proc greet {} {return ok}\n'),
            ('file:///second.tcl', 'proc greet {} {return ok}\n'),
        ),
        target_uri='file:///first.tcl',
    )
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['duplicate-proc']
