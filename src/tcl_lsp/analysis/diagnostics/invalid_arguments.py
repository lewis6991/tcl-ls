from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.model import ProcDecl
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import command_target_structured_matches, resolved_command_calls


class InvalidArgumentsChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'invalid-arguments'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, command_target in resolved_command_calls(context):
            if isinstance(command_target, ProcDecl):
                continue

            structured_matches = command_target_structured_matches(command_call, command_target)
            if structured_matches is None:
                continue
            if any(state in {'exact', 'dynamic'} for _, _, state in structured_matches):
                continue

            expected_signatures = tuple(
                dict.fromkeys(
                    signature for signature, arity_matches, _ in structured_matches if arity_matches
                )
            )
            if not expected_signatures:
                continue

            command_name = command_call.name or '<dynamic>'
            if len(expected_signatures) == 1:
                message = (
                    f'Invalid arguments for command `{command_name}`; '
                    f'expected `{expected_signatures[0]}`.'
                )
            else:
                expected = (
                    ', '.join(f'`{signature}`' for signature in expected_signatures[:-1])
                    + f', or `{expected_signatures[-1]}`'
                )
                message = (
                    f'Invalid arguments for command `{command_name}`; expected one of: {expected}.'
                )
            yield self.emit(span=command_call.span, message=message)
