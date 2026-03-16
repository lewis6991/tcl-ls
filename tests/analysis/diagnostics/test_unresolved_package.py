from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_reports_unresolved_packages(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///missing_package.tcl',
        'package require missing\n',
    )
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['unresolved-package']
    assert analysis.diagnostics[0].message == 'Unresolved package `missing`.'
