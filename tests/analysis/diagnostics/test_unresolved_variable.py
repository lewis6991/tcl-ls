from __future__ import annotations

from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def test_analysis_preserves_diagnostic_spans_across_braced_line_continuations(
    parser: Parser,
) -> None:
    source = (
        'namespace eval Markdown {\n'
        '    proc collect_references {line} {\n'
        '        if {[regexp \\\n'
        '                 {^foo$} \\\n'
        '                 $line \\\n'
        '                 match]\n'
        '        } {\n'
        '            return ok\n'
        '        }\n'
        '    }\n'
        '    proc parse_inline {} {\n'
        '        regexp {^\\s*#+} $line m\n'
        '    }\n'
        '}\n'
    )
    snapshot = _analyze(
        parser,
        'file:///markdown_like.tcl',
        source,
    )

    unresolved_variables = [
        diagnostic
        for diagnostic in snapshot.analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    ]
    assert len(unresolved_variables) == 1

    diagnostic = unresolved_variables[0]
    assert diagnostic.message == 'Unresolved variable `line`.'
    assert diagnostic.span.start.line == 11
    assert source[diagnostic.span.start.offset : diagnostic.span.end.offset] == '$line'
