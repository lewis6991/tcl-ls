from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.model import (
    AnalysisResult,
    AnalysisUncertainty,
    CommandCall,
    DefinitionTarget,
    DocumentFacts,
    ProcDecl,
    ReferenceSite,
    ResolutionResult,
    ResolvedReference,
    VarBinding,
    VariableReference,
)
from tcl_lsp.common import Diagnostic, HoverInfo, Location

_BUILTIN_COMMANDS = {
    'after',
    'append',
    'apply',
    'array',
    'binary',
    'break',
    'catch',
    'cd',
    'chan',
    'clock',
    'close',
    'concat',
    'continue',
    'coroutine',
    'dict',
    'encoding',
    'eof',
    'error',
    'eval',
    'exec',
    'exit',
    'expr',
    'fblocked',
    'fconfigure',
    'fcopy',
    'file',
    'fileevent',
    'flush',
    'for',
    'foreach',
    'format',
    'gets',
    'global',
    'glob',
    'if',
    'incr',
    'info',
    'interp',
    'join',
    'lappend',
    'lassign',
    'lindex',
    'linsert',
    'list',
    'llength',
    'lmap',
    'load',
    'lrange',
    'lrepeat',
    'lreplace',
    'lreverse',
    'lsearch',
    'lset',
    'lsort',
    'namespace',
    'open',
    'package',
    'pid',
    'proc',
    'puts',
    'read',
    'regexp',
    'regsub',
    'rename',
    'return',
    'scan',
    'seek',
    'set',
    'socket',
    'source',
    'split',
    'string',
    'subst',
    'switch',
    'tailcall',
    'tell',
    'time',
    'trace',
    'try',
    'unset',
    'update',
    'uplevel',
    'upvar',
    'variable',
    'vwait',
    'while',
    'yield',
    'yieldto',
    'zlib',
}
_BUILTIN_PACKAGES = {'Tcl'}


@dataclass(frozen=True, slots=True)
class _BindingSummary:
    binding: VarBinding
    detail: str


class Resolver:
    def analyze(
        self, uri: str, facts: DocumentFacts, workspace_index: WorkspaceIndex
    ) -> AnalysisResult:
        diagnostics: list[Diagnostic] = list(facts.diagnostics)
        definitions = self._build_definitions(facts)
        definition_by_symbol = {definition.symbol_id: definition for definition in definitions}
        binding_lookup = self._build_binding_lookup(facts.variable_bindings)
        hovers = self._build_definition_hovers(definitions)
        required_packages = frozenset(requirement.name for requirement in facts.package_requires)

        resolutions: list[ResolutionResult] = []
        resolved_references: list[ResolvedReference] = []

        for proc in facts.procedures:
            duplicates = workspace_index.procedures_for_name(proc.qualified_name)
            if len(duplicates) > 1:
                diagnostics.append(
                    Diagnostic(
                        span=proc.name_span,
                        severity='error',
                        message=f'Procedure `{proc.qualified_name}` is declared multiple times.',
                        source='analysis',
                        code='duplicate-proc',
                    )
                )

        for package_require in facts.package_requires:
            if package_require.name in _BUILTIN_PACKAGES or workspace_index.has_package(
                package_require.name
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    span=package_require.span,
                    severity='warning',
                    message=f'Unresolved package `{package_require.name}`.',
                    source='analysis',
                    code='unresolved-package',
                )
            )

        for command_call in facts.command_calls:
            resolution, command_hover = self._resolve_command(
                command_call,
                workspace_index,
                required_packages,
            )
            resolutions.append(resolution)
            if command_hover is not None:
                hovers.append(command_hover)
            if resolution.uncertainty.state == 'resolved':
                for symbol_id in resolution.target_symbol_ids:
                    resolved_references.append(
                        ResolvedReference(
                            symbol_id=symbol_id,
                            reference=resolution.reference,
                        )
                    )
            if resolution.uncertainty.state == 'unresolved':
                diagnostics.append(
                    Diagnostic(
                        span=command_call.name_span,
                        severity='warning',
                        message=f'Unresolved command `{command_call.name}`.',
                        source='analysis',
                        code='unresolved-command',
                    )
                )
            if resolution.uncertainty.state == 'ambiguous':
                diagnostics.append(
                    Diagnostic(
                        span=command_call.name_span,
                        severity='warning',
                        message=f'Command `{command_call.name}` resolves to multiple procedures.',
                        source='analysis',
                        code='ambiguous-command',
                    )
                )

        for variable_reference in facts.variable_references:
            resolution, variable_hover = self._resolve_variable(
                variable_reference,
                binding_lookup,
                definition_by_symbol,
            )
            resolutions.append(resolution)
            if variable_hover is not None:
                hovers.append(variable_hover)
            if resolution.uncertainty.state == 'resolved':
                for symbol_id in resolution.target_symbol_ids:
                    resolved_references.append(
                        ResolvedReference(
                            symbol_id=symbol_id,
                            reference=resolution.reference,
                        )
                    )
            if (
                resolution.uncertainty.state == 'unresolved'
                and variable_reference.procedure_symbol_id is not None
            ):
                diagnostics.append(
                    Diagnostic(
                        span=variable_reference.span,
                        severity='warning',
                        message=f'Unresolved variable `{variable_reference.name}`.',
                        source='analysis',
                        code='unresolved-variable',
                    )
                )

        return AnalysisResult(
            uri=uri,
            diagnostics=tuple(diagnostics),
            definitions=tuple(definitions),
            resolutions=tuple(resolutions),
            resolved_references=tuple(resolved_references),
            document_symbols=facts.document_symbols,
            hovers=tuple(hovers),
        )

    def _build_definitions(self, facts: DocumentFacts) -> list[DefinitionTarget]:
        definitions: list[DefinitionTarget] = []
        for proc in facts.procedures:
            definitions.append(
                DefinitionTarget(
                    symbol_id=proc.symbol_id,
                    name=proc.qualified_name,
                    kind='function',
                    location=Location(uri=proc.uri, span=proc.name_span),
                    detail=_proc_hover(proc),
                )
            )

        first_binding_by_symbol: dict[str, VarBinding] = {}
        for binding in sorted(facts.variable_bindings, key=lambda item: item.span.start.offset):
            first_binding_by_symbol.setdefault(binding.symbol_id, binding)

        for binding in first_binding_by_symbol.values():
            definitions.append(
                DefinitionTarget(
                    symbol_id=binding.symbol_id,
                    name=binding.name,
                    kind='variable',
                    location=Location(uri=binding.uri, span=binding.span),
                    detail=f'{binding.kind} {binding.name}',
                )
            )

        return definitions

    def _build_binding_lookup(
        self, bindings: tuple[VarBinding, ...]
    ) -> dict[tuple[str, str], tuple[_BindingSummary, ...]]:
        bindings_by_key: dict[tuple[str, str], list[VarBinding]] = {}
        for binding in sorted(bindings, key=lambda item: item.span.start.offset):
            bindings_by_key.setdefault((binding.scope_id, binding.name), []).append(binding)

        result: dict[tuple[str, str], tuple[_BindingSummary, ...]] = {}
        for key, candidates in bindings_by_key.items():
            summaries: dict[str, _BindingSummary] = {}
            for candidate in candidates:
                summaries.setdefault(
                    candidate.symbol_id,
                    _BindingSummary(binding=candidate, detail=f'{candidate.kind} {candidate.name}'),
                )
            result[key] = tuple(summaries.values())
        return result

    def _build_definition_hovers(self, definitions: list[DefinitionTarget]) -> list[HoverInfo]:
        return [
            HoverInfo(span=definition.location.span, contents=definition.detail)
            for definition in definitions
        ]

    def _resolve_command(
        self,
        command_call: CommandCall,
        workspace_index: WorkspaceIndex,
        required_packages: frozenset[str],
    ) -> tuple[ResolutionResult, HoverInfo | None]:
        reference = ReferenceSite(
            uri=command_call.uri,
            kind='command',
            name=command_call.name,
            namespace=command_call.namespace,
            scope_id=command_call.scope_id,
            procedure_symbol_id=command_call.procedure_symbol_id,
            span=command_call.name_span,
            dynamic=command_call.dynamic,
        )

        if command_call.dynamic or command_call.name is None:
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='dynamic',
                        reason='Command name is computed dynamically.',
                    ),
                    target_symbol_ids=(),
                ),
                None,
            )

        builtin_name = _normalize_command_name(command_call.name)
        if builtin_name in _BUILTIN_COMMANDS:
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='dynamic',
                        reason='Built-in Tcl commands are not indexed as definitions.',
                    ),
                    target_symbol_ids=(),
                ),
                HoverInfo(
                    span=command_call.name_span,
                    contents=f'builtin command {builtin_name}',
                ),
            )

        matches = workspace_index.resolve_procedure(command_call.name, command_call.namespace)
        if not matches:
            package_name = _matching_required_package(command_call.name, required_packages)
            if package_name is not None:
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='dynamic',
                            reason=f'Command may be provided by required package `{package_name}`.',
                        ),
                        target_symbol_ids=(),
                    ),
                    None,
                )
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='unresolved',
                        reason='No matching procedure was indexed in the workspace.',
                    ),
                    target_symbol_ids=(),
                ),
                None,
            )
        if len(matches) > 1:
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='ambiguous',
                        reason='Multiple procedures match this command name.',
                    ),
                    target_symbol_ids=tuple(match.symbol_id for match in matches),
                ),
                None,
            )
        if len(matches) == 1:
            proc = matches[0]
            detail = _proc_hover(proc)
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='resolved',
                        reason='Resolved to a unique procedure definition.',
                    ),
                    target_symbol_ids=(proc.symbol_id,),
                ),
                HoverInfo(span=command_call.name_span, contents=detail),
            )

        return (
            ResolutionResult(
                reference=reference,
                uncertainty=AnalysisUncertainty(
                    state='dynamic',
                    reason='Command resolution did not fit a supported static case.',
                ),
                target_symbol_ids=(),
            ),
            None,
        )

    def _resolve_variable(
        self,
        variable_reference: VariableReference,
        binding_lookup: dict[tuple[str, str], tuple[_BindingSummary, ...]],
        definition_by_symbol: dict[str, DefinitionTarget],
    ) -> tuple[ResolutionResult, HoverInfo | None]:
        reference = ReferenceSite(
            uri=variable_reference.uri,
            kind='variable',
            name=variable_reference.name,
            namespace=variable_reference.namespace,
            scope_id=variable_reference.scope_id,
            procedure_symbol_id=variable_reference.procedure_symbol_id,
            span=variable_reference.span,
            dynamic=False,
        )

        matches = binding_lookup.get((variable_reference.scope_id, variable_reference.name), ())
        if not matches:
            state = 'dynamic' if variable_reference.procedure_symbol_id is None else 'unresolved'
            reason = (
                'Global variable resolution is intentionally conservative.'
                if variable_reference.procedure_symbol_id is None
                else 'No matching binding was collected in this procedure scope.'
            )
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(state=state, reason=reason),
                    target_symbol_ids=(),
                ),
                None,
            )

        symbol_ids = tuple(summary.binding.symbol_id for summary in matches)
        hover = None
        if len(symbol_ids) == 1:
            definition = definition_by_symbol.get(symbol_ids[0])
            if definition is not None:
                hover = HoverInfo(span=variable_reference.span, contents=definition.detail)
        state = 'resolved' if len(symbol_ids) == 1 else 'ambiguous'
        reason = (
            'Resolved to a unique variable binding.'
            if len(symbol_ids) == 1
            else 'Multiple variable bindings share this name in scope.'
        )
        return (
            ResolutionResult(
                reference=reference,
                uncertainty=AnalysisUncertainty(state=state, reason=reason),
                target_symbol_ids=symbol_ids,
            ),
            hover,
        )


def _proc_detail(proc: ProcDecl) -> str:
    parameters = ', '.join(parameter.name for parameter in proc.parameters)
    return f'proc {proc.qualified_name}({parameters})'


def _proc_hover(proc: ProcDecl) -> str:
    detail = _proc_detail(proc)
    if proc.documentation is None:
        return detail
    return f'{detail}\n\n{proc.documentation}'


def _normalize_command_name(name: str) -> str:
    return name[2:] if name.startswith('::') else name


def _matching_required_package(
    command_name: str,
    required_packages: frozenset[str],
) -> str | None:
    normalized_name = _normalize_command_name(command_name)
    for package_name in sorted(required_packages):
        if normalized_name == package_name or normalized_name.startswith(f'{package_name}::'):
            return package_name
    return None
