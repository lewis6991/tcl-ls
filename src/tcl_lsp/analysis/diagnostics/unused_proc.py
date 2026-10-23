from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.facts.utils import name_tail
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

        def record_use(name: str, namespace: str, caller: str | None) -> None:
            targets = usage_index.resolve_procedure(name, namespace)
            if not targets:
                targets = usage_index.imported_procedures_for_name(name, namespace)
            used.update(proc.symbol_id for proc in targets if proc.symbol_id != caller)

        for facts in usage_index.documents():
            declaration_spans = {proc.span for proc in facts.procedures}
            for call in facts.command_calls:
                if facts.uri != context.facts.uri and call.name is not None:
                    record_use(call.name, call.namespace, call.procedure_symbol_id)
                if call.span in declaration_spans:
                    continue
                # A literal command name or command prefix can escape as a
                # callback. Procedure declarations themselves are not uses.
                for argument, span in zip(call.arg_texts, call.arg_spans, strict=True):
                    if argument is None:
                        continue
                    words = split_tcl_list(argument, span.start)
                    if words and name_tail(words[0].text).startswith('_'):
                        record_use(words[0].text, call.namespace, call.procedure_symbol_id)
            for rename in facts.command_renames:
                record_use(rename.old_name, rename.namespace, rename.procedure_symbol_id)

        for symbol_id, proc in candidates.items():
            if symbol_id in used:
                continue
            yield self.emit(
                span=proc.name_span,
                message=f'Procedure `{proc.qualified_name}` is unused.',
                tags=('unnecessary',),
            )
