from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class UnknownOptionChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unknown-option'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, state, option_name, span in context.option_issues:
            if state != self.CODE:
                continue
            command_name = command_call.name or '<dynamic>'
            yield self.emit(
                span=span,
                message=f'Unknown option `{option_name}` for command `{command_name}`.',
            )
