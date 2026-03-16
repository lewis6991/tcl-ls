from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class UnresolvedVariableChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unresolved-variable'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'warning'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for resolved_variable in context.variable_resolutions:
            variable_reference = resolved_variable.variable_reference
            if (
                resolved_variable.resolution.uncertainty.state != 'unresolved'
                or variable_reference.procedure_symbol_id is None
            ):
                continue
            yield self.emit(
                span=variable_reference.span,
                message=f'Unresolved variable `{variable_reference.name}`.',
            )
