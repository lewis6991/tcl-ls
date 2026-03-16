from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class UnresolvedCommandChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unresolved-command'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'warning'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for resolved_command in context.command_resolutions:
            if resolved_command.resolution.uncertainty.state != 'unresolved':
                continue
            command_call = resolved_command.command_call
            command_name = command_call.name or '<dynamic>'
            yield self.emit(
                span=command_call.name_span,
                message=f'Unresolved command `{command_name}`.',
            )
