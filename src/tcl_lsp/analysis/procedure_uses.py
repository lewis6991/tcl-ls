from __future__ import annotations

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.facts.utils import name_tail
from tcl_lsp.analysis.model import DocumentFacts, ProcedureUse, ProcedureUses


def collect_procedure_uses(facts: DocumentFacts) -> ProcedureUses:
    """Collect possible uses without resolving names against other files."""
    calls: dict[ProcedureUse, None] = {}
    references: dict[ProcedureUse, None] = {}
    declaration_spans = {proc.span for proc in facts.procedures}
    for call in facts.command_calls:
        if call.name is not None:
            calls[ProcedureUse(call.name, call.namespace, call.procedure_symbol_id)] = None
        if call.span in declaration_spans:
            continue
        # Literal command names and prefixes can escape as callbacks.
        for argument, span in zip(call.arg_texts, call.arg_spans, strict=True):
            if argument is None or ('_' not in argument and '\\' not in argument):
                continue
            words = split_tcl_list(argument, span.start, max_items=1)
            if words and name_tail(words[0].text).startswith('_'):
                references[
                    ProcedureUse(words[0].text, call.namespace, call.procedure_symbol_id)
                ] = None
    for rename in facts.command_renames:
        use = ProcedureUse(rename.old_name, rename.namespace, rename.procedure_symbol_id)
        references[use] = None
    return ProcedureUses(tuple(calls), tuple(references))
