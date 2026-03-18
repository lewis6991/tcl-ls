from __future__ import annotations

import shutil

import pytest

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze

tclsh = shutil.which('tclsh')
pytestmark = pytest.mark.skipif(tclsh is None, reason='tclsh not found')


def test_analysis_reports_invalid_regexp_patterns(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///invalid_regexp.tcl', 'regexp {(} text\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['invalid-regex']
    diagnostic = analysis.diagnostics[0]
    assert diagnostic.message.startswith('Invalid regular expression for command `regexp`;')
    assert diagnostic.message.endswith('.')
    assert diagnostic.span.start.character == 7


def test_analysis_reports_invalid_regsub_patterns(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///invalid_regsub.tcl', 'regsub {(} text x\n')
    analysis = snapshot.analysis

    assert [diagnostic.code for diagnostic in analysis.diagnostics] == ['invalid-regex']
    diagnostic = analysis.diagnostics[0]
    assert diagnostic.message.startswith('Invalid regular expression for command `regsub`;')
    assert diagnostic.message.endswith('.')
    assert diagnostic.span.start.character == 7


def test_analysis_accepts_valid_regexp_patterns(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///valid_regexp.tcl', 'regexp {(..)} text\n')
    assert snapshot.analysis.diagnostics == ()
