from __future__ import annotations

import json
from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.model import ProcDecl
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import resolved_command_calls


class IncompatibleEnvironmentChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'incompatible-environment'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'warning'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for call, target in resolved_command_calls(context):
            if not isinstance(target, ProcDecl) or not target.global_requirements:
                continue
            known = dict(call.global_values)
            for name, permitted in target.global_requirements:
                values = known.get(name, ())
                if not values or all(value in permitted for value in values):
                    continue
                expected = ' or '.join(json.dumps(value) for value in permitted)
                actual = ' or '.join(json.dumps(value) for value in values)
                yield self.emit(
                    span=call.name_span,
                    message=(
                        f'Call to `{target.qualified_name}` requires `{name}` to be '
                        f'{expected}; current value is {actual}.'
                    ),
                )
