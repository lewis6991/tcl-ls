from __future__ import annotations

from lsprotocol import types

from tcl_lsp.common import Diagnostic, lsp_range

_SEVERITIES = {
    'error': types.DiagnosticSeverity.Error,
    'warning': types.DiagnosticSeverity.Warning,
    'information': types.DiagnosticSeverity.Information,
    'hint': types.DiagnosticSeverity.Hint,
}
_TAGS = {
    'deprecated': types.DiagnosticTag.Deprecated,
    'unnecessary': types.DiagnosticTag.Unnecessary,
}


def lsp_diagnostic(diagnostic: Diagnostic) -> types.Diagnostic:
    return types.Diagnostic(
        range=lsp_range(diagnostic.span),
        severity=_SEVERITIES[diagnostic.severity],
        code=diagnostic.code,
        source=diagnostic.source,
        message=diagnostic.message,
        tags=[_TAGS[tag] for tag in diagnostic.tags] or None,
    )
