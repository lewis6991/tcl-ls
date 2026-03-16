from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import command_subcommand_issue, resolved_command_calls


class UnknownSubcommandChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unknown-subcommand'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, command_target in resolved_command_calls(context):
            issue = command_subcommand_issue(command_call, command_target)
            if issue is None:
                continue

            subcommand_name, span = issue
            command_name = command_call.name or '<dynamic>'
            yield self.emit(
                span=span,
                message=f'Unknown subcommand `{subcommand_name}` for command `{command_name}`.',
            )
