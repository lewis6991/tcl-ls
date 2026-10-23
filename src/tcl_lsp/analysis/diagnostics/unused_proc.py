from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.facts.utils import name_tail
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class UnusedProcChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unused-proc'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'hint'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        candidates = {
            proc.symbol_id: proc
            for proc in context.facts.procedures
            if name_tail(proc.qualified_name).startswith('_') and proc.body_span is not None
        }
        if not candidates:
            return
        usage_index = context.usage_index or context.workspace_index

        used: set[str] = set()
        for resolved in context.command_resolutions:
            used.update(
                symbol_id
                for symbol_id in resolved.resolution.target_symbol_ids
                if symbol_id != resolved.command_call.procedure_symbol_id
            )

        used.update(used_procedure_ids(usage_index, skip_calls_in=context.facts.uri))

        for symbol_id, proc in candidates.items():
            if symbol_id in used:
                continue
            yield self.emit(
                span=proc.name_span,
                message=f'Procedure `{proc.qualified_name}` is unused.',
                tags=('unnecessary',),
            )


def used_procedure_ids(index: WorkspaceIndex, *, skip_calls_in: str | None = None) -> set[str]:
    """Collect possible procedure uses once for a prepared project index."""
    used: set[str] = set()

    def record_use(name: str, namespace: str, caller: str | None) -> None:
        targets = index.resolve_procedure(name, namespace)
        if not targets:
            targets = index.imported_procedures_for_name(name, namespace)
        used.update(proc.symbol_id for proc in targets if proc.symbol_id != caller)

    for facts in index.documents():
        uses = facts.procedure_uses
        if facts.uri != skip_calls_in:
            for call in uses.calls:
                record_use(call.name, call.namespace, call.procedure_symbol_id)
        for reference in uses.references:
            record_use(reference.name, reference.namespace, reference.procedure_symbol_id)
    return used
