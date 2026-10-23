from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.builtins import registry_for_packages
from tcl_lsp.analysis.embedded_languages import ContextualCommand
from tcl_lsp.analysis.flow import normalize_variable_name
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataContext,
    MetadataPlugin,
    MetadataProcedure,
    MetadataRef,
    select_argument_indices,
)
from tcl_lsp.analysis.metadata_view import metadata_view
from tcl_lsp.analysis.model import CommandCall, ProcDecl, VarBinding
from tcl_lsp.analysis.modules import registry_at_offset
from tcl_lsp.common import Diagnostic

from .base import (
    AnalysisDiagnosticSeverity,
    DiagnosticChecker,
    DiagnosticContext,
    ResolvedCommandTarget,
)
from .helpers import command_call_key

_LINK_KINDS = frozenset({'global', 'variable', 'upvar'})


class UnusedVariableChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unused-variable'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'hint'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        bindings: dict[tuple[str, str], list[VarBinding]] = defaultdict(list)
        for binding in context.facts.variable_bindings:
            if binding.procedure_symbol_id is not None:
                bindings[binding.scope_id, binding.name].append(binding)

        # A link declaration is a reference for navigation, but does not use
        # the local link. Uses in other procedures do not use this link either.
        declarations = {
            (binding.scope_id, binding.name, binding.span)
            for group in bindings.values()
            for binding in group
            if binding.kind in _LINK_KINDS
        }
        used = {
            (reference.scope_id, reference.name)
            for reference in context.facts.variable_references
            if (reference.scope_id, reference.name, reference.span) not in declarations
        }
        uncertain_scopes: set[str] = set()
        for call in context.facts.command_calls:
            if call.procedure_symbol_id is None:
                continue
            target = context.command_targets.get(command_call_key(call))
            if _has_hidden_uses(call, target, context):
                uncertain_scopes.add(call.scope_id)

            if target is None or isinstance(target, ProcDecl):
                # A helper can receive a variable name and use upvar. Metadata
                # ref annotations give more precise uses for known commands.
                used.update(
                    (call.scope_id, normalize_variable_name(arg))
                    for arg in call.arg_texts
                    if arg is not None
                )
            elif target.name == 'upvar':
                # Even a same-frame alias can read an existing local variable.
                start = 1 if call.arg_texts and _is_level(call.arg_texts[0]) else 0
                used.update(
                    (call.scope_id, normalize_variable_name(arg))
                    for arg in call.arg_texts[start::2]
                    if arg is not None
                )
            elif target.name == 'variable':
                used.update(
                    (call.scope_id, arg.rsplit('::', 1)[-1])
                    for arg in call.arg_texts[:-1:2]
                    if arg is not None
                )

        for key, group in bindings.items():
            binding = min(group, key=lambda item: item.span.start.offset)
            if key in used or binding.scope_id in uncertain_scopes or binding.name.startswith('_'):
                continue
            # Writes through a link can affect another scope without a local
            # read. Only an unused, uninitialised link is a candidate.
            if any(item.kind in _LINK_KINDS for item in group) and any(
                item.kind not in _LINK_KINDS for item in group
            ):
                continue
            yield self.emit(
                span=binding.span,
                message=f'Variable `{binding.name}` is unused.',
                tags=('unnecessary',),
            )


def _has_hidden_uses(
    call: CommandCall,
    target: ResolvedCommandTarget | None,
    context: DiagnosticContext,
) -> bool:
    if target is None or isinstance(target, ProcDecl):
        return call.dynamic or call.has_expanded_args or any(arg is None for arg in call.arg_texts)
    name = target.name
    if name in {'eval', 'uplevel', 'source', 'subst', 'trace'}:
        return True
    if name == 'info' and (
        not call.arg_texts
        or call.arg_texts[0] is None
        or any(subcommand.startswith(call.arg_texts[0]) for subcommand in ('locals', 'vars'))
    ):
        return True
    if name in {'expr', 'if', 'while', 'for', 'catch', 'try', 'switch'} and any(
        arg is None for arg in call.arg_texts
    ):
        return True

    # These core commands collect variable names directly, outside metadata.
    indices: Iterable[int] = ()
    if name == 'variable':
        indices = range(0, len(call.arg_texts), 2)
    elif name in {'set', 'global', 'upvar', 'unset'}:
        indices = (
            range(len(call.arg_texts)) if name != 'set' else range(min(1, len(call.arg_texts)))
        )
    elif name == 'array' or (name == 'info' and call.arg_texts[:1] == ('exists',)):
        indices = range(1, min(2, len(call.arg_texts)))
    elif name.startswith('trace '):
        # A trace observes writes as well as reads. Until trace references are
        # collected, keep the procedure's variables conservative.
        return True
    if any(call.arg_texts[index] is None or call.arg_expanded[index] for index in indices):
        return True

    if isinstance(target, ContextualCommand):
        overloads = target.overloads
    else:
        registry = registry_at_offset(
            context.metadata_registry, context.facts.module_scopes, call.span.start.offset
        )
        registry = registry_for_packages(registry, context.required_packages)
        overloads = metadata_view(registry).commands.get((None, name), ())
    for overload in overloads:
        for annotation in overload.annotations:
            if isinstance(annotation, MetadataPlugin) or (
                isinstance(annotation, MetadataProcedure)
                and annotation.parameter_plugin is not None
            ):
                return True
            if isinstance(annotation, MetadataContext):
                selector = annotation.body_selector
            elif isinstance(annotation, (MetadataRef, MetadataBind)):
                selector = annotation.selector
            else:
                continue
            selected = select_argument_indices(
                selector, call.arg_texts, overload.options, call.arg_expanded
            )
            if selected is None or any(call.arg_texts[index] is None for index in selected):
                return True
    return False


def _is_level(text: str | None) -> bool:
    return text is not None and (text.isdigit() or text.startswith('#'))
