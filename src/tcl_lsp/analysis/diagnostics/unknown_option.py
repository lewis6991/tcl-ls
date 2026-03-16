from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import command_option_issue, resolved_command_calls


class UnknownOptionChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unknown-option'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, command_target in resolved_command_calls(context):
            issue = command_option_issue(command_call, command_target)
            if issue is None:
                continue
            state, option_name, span = issue
            if state != self.CODE:
                continue
            command_name = command_call.name or '<dynamic>'
            yield self.emit(
                span=span,
                message=f'Unknown option `{option_name}` for command `{command_name}`.',
            )
