from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.embedded_languages import ContextualCommand
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import resolved_command_calls


class ValueConstraintChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'invalid-expr-operand'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        owners = {
            call.span: target.name
            for call, target in resolved_command_calls(context)
            if isinstance(target, (BuiltinCommand, ContextualCommand))
        }
        for check in context.facts.value_checks:
            if owners.get(check.command_span) == check.command_name:
                yield check.diagnostic
