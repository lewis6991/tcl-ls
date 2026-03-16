from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class DuplicateProcChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'duplicate-proc'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for proc in context.facts.procedures:
            duplicates = context.workspace_index.procedures_for_name(proc.qualified_name)
            if len(duplicates) <= 1:
                continue
            yield self.emit(
                span=proc.name_span,
                message=f'Procedure `{proc.qualified_name}` is declared multiple times.',
            )
