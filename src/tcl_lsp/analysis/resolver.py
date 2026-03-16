from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from tcl_lsp.analysis.builtins import (
    BuiltinCommand,
    builtin_commands_any,
    builtin_commands_for_packages,
)
from tcl_lsp.analysis.embedded_languages import (
    contextual_resolution_reason,
    resolves_contextual_command,
)
from tcl_lsp.analysis.diagnostics import (
    DiagnosticContext,
    ResolvedCommand,
    ResolvedCommandTarget,
    ResolvedVariable,
    collect_diagnostics,
)
from tcl_lsp.analysis.diagnostics.helpers import command_call_key
from tcl_lsp.analysis.facts.parsing import is_simple_name, split_tcl_list
from tcl_lsp.analysis.facts.utils import name_tail, variable_symbol_id
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataCommand,
    all_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.analysis.model import (
    AnalysisResult,
    AnalysisUncertainty,
    BINDING_KINDS,
    BindingKind,
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
from tcl_lsp.common import HoverInfo, Location, Span
from tcl_lsp.workspace import source_id_to_path


@dataclass(frozen=True, slots=True)
class _BindingSummary:
    binding: VarBinding
    detail: str


class Resolver:
    __slots__ = ()

    def analyze(
        self,
        uri: str,
        facts: DocumentFacts,
        workspace_index: WorkspaceIndex,
        *,
        additional_required_packages: frozenset[str] = frozenset(),
    ) -> AnalysisResult:
        diagnostics = list(facts.diagnostics)
        required_packages = frozenset(requirement.name for requirement in facts.package_requires)
        required_packages |= additional_required_packages

        resolutions: list[ResolutionResult] = []
        resolved_references: list[ResolvedReference] = []
        command_targets: dict[tuple[str, int, int, int, int], ResolvedCommandTarget] = {}
        command_resolutions: list[ResolvedCommand] = []
        resolved_command_targets: list[tuple[CommandCall, ResolvedCommandTarget]] = []
        command_hovers: list[HoverInfo] = []

        for command_call in facts.command_calls:
            resolution, command_hover, command_target = self._resolve_command(
                command_call,
                workspace_index,
                required_packages,
            )
            resolutions.append(resolution)
            command_resolutions.append(
                ResolvedCommand(
                    command_call=command_call,
                    resolution=resolution,
                )
            )
            if command_target is not None:
                command_targets[command_call_key(command_call)] = command_target
                resolved_command_targets.append((command_call, command_target))
            if command_hover is not None:
                command_hovers.append(command_hover)
            if resolution.uncertainty.state == 'resolved':
                for symbol_id in resolution.target_symbol_ids:
                    resolved_references.append(
                        ResolvedReference(
                            symbol_id=symbol_id,
                            reference=resolution.reference,
                        )
                    )

        metadata_bindings = self._metadata_bindings(
            facts.variable_bindings,
            resolved_command_targets,
        )
        all_bindings = facts.variable_bindings + metadata_bindings
        definitions = self._build_definitions(facts, all_bindings)
        definition_by_symbol = {definition.symbol_id: definition for definition in definitions}
        binding_lookup = self._build_binding_lookup(all_bindings)
        hovers = self._build_definition_hovers(definitions)
        hovers.extend(command_hovers)

        variable_resolutions: list[ResolvedVariable] = []

        for variable_reference in facts.variable_references:
            resolution, variable_hover = self._resolve_variable(
                variable_reference,
                binding_lookup,
                definition_by_symbol,
            )
            resolutions.append(resolution)
            variable_resolutions.append(
                ResolvedVariable(
                    variable_reference=variable_reference,
                    resolution=resolution,
                )
            )
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

        diagnostics.extend(
            collect_diagnostics(
                DiagnosticContext(
                    facts=facts,
                    workspace_index=workspace_index,
                    required_packages=required_packages,
                    command_targets=command_targets,
                    command_resolutions=tuple(command_resolutions),
                    variable_resolutions=tuple(variable_resolutions),
                )
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

    def _build_definitions(
        self,
        facts: DocumentFacts,
        bindings: tuple[VarBinding, ...],
    ) -> list[DefinitionTarget]:
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
        for binding in sorted(bindings, key=lambda item: item.span.start.offset):
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

    def _metadata_bindings(
        self,
        existing_bindings: tuple[VarBinding, ...],
        resolved_command_targets: list[tuple[CommandCall, ResolvedCommandTarget]],
    ) -> tuple[VarBinding, ...]:
        symbol_ids_by_key: dict[tuple[str, str], str] = {}
        for binding in existing_bindings:
            symbol_ids_by_key.setdefault((binding.scope_id, binding.name), binding.symbol_id)

        metadata_bindings: list[VarBinding] = []
        for command_call, target in resolved_command_targets:
            metadata_command = _metadata_command_for_target(target)
            if metadata_command is None:
                continue

            for annotation in metadata_command.annotations:
                if not isinstance(annotation, MetadataBind):
                    continue

                selected_indices = select_argument_indices(
                    annotation.selector,
                    command_call.arg_texts,
                    metadata_command.options,
                    command_call.arg_expanded,
                )
                if selected_indices is None:
                    continue

                binding_kind = _metadata_binding_kind(metadata_command, annotation)
                for index in selected_indices:
                    if index >= len(command_call.arg_texts):
                        continue

                    argument_text = command_call.arg_texts[index]
                    if argument_text is None:
                        continue

                    argument_span = command_call.arg_spans[index]
                    if annotation.selector.list_mode:
                        for item in split_tcl_list(argument_text, argument_span.start):
                            binding = _metadata_var_binding(
                                command_call,
                                item.text,
                                item.span,
                                binding_kind,
                                symbol_ids_by_key,
                            )
                            if binding is None:
                                continue
                            metadata_bindings.append(binding)
                        continue

                    binding = _metadata_var_binding(
                        command_call,
                        argument_text,
                        argument_span,
                        binding_kind,
                        symbol_ids_by_key,
                    )
                    if binding is None:
                        continue
                    metadata_bindings.append(binding)

        return tuple(metadata_bindings)

    def _resolve_command(
        self,
        command_call: CommandCall,
        workspace_index: WorkspaceIndex,
        required_packages: frozenset[str],
    ) -> tuple[ResolutionResult, HoverInfo | None, ResolvedCommandTarget | None]:
        reference = ReferenceSite(
            uri=command_call.uri,
            kind='command',
            name=command_call.name,
            namespace=command_call.namespace,
            scope_id=command_call.scope_id,
            procedure_symbol_id=command_call.procedure_symbol_id,
            embedded_language=command_call.embedded_language,
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
                None,
            )

        builtin_name = _normalize_command_name(command_call.name)
        if resolves_contextual_command(command_call.embedded_language, builtin_name):
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='resolved',
                        reason=contextual_resolution_reason(
                            command_call.embedded_language,
                            builtin_name,
                        ),
                    ),
                    target_symbol_ids=(),
                ),
                None,
                None,
            )

        builtin_matches = builtin_commands_for_packages(builtin_name, required_packages)
        if len(builtin_matches) == 1:
            builtin = builtin_matches[0]
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='resolved',
                        reason=_builtin_resolution_reason(builtin),
                    ),
                    target_symbol_ids=tuple(overload.symbol_id for overload in builtin.overloads),
                ),
                HoverInfo(
                    span=command_call.name_span,
                    contents=_builtin_hover(builtin),
                ),
                builtin,
            )
        if len(builtin_matches) > 1:
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='ambiguous',
                        reason='Multiple bundled command metadata entries match this command name.',
                    ),
                    target_symbol_ids=tuple(
                        overload.symbol_id
                        for builtin in builtin_matches
                        for overload in builtin.overloads
                    ),
                ),
                None,
                None,
            )
        if '::' in builtin_name:
            qualified_builtin_matches = builtin_commands_any(builtin_name)
            if len(qualified_builtin_matches) == 1:
                builtin = qualified_builtin_matches[0]
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='resolved',
                            reason=(
                                'Resolved to bundled package metadata by fully '
                                'qualified command name.'
                            ),
                        ),
                        target_symbol_ids=tuple(
                            overload.symbol_id for overload in builtin.overloads
                        ),
                    ),
                    HoverInfo(
                        span=command_call.name_span,
                        contents=_builtin_hover(builtin),
                    ),
                    builtin,
                )
            if len(qualified_builtin_matches) > 1:
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='ambiguous',
                            reason=(
                                'Multiple bundled package metadata entries match '
                                'this fully qualified command name.'
                            ),
                        ),
                        target_symbol_ids=tuple(
                            overload.symbol_id
                            for builtin in qualified_builtin_matches
                            for overload in builtin.overloads
                        ),
                    ),
                    None,
                    None,
                )

        matches = workspace_index.resolve_procedure(command_call.name, command_call.namespace)
        resolved_via_import = False
        if not matches:
            matches = workspace_index.resolve_imported_procedure(
                command_call.name,
                command_call.namespace,
            )
            resolved_via_import = bool(matches)
        builtin_from_import = None
        if not matches:
            imported_builtin_matches = self._resolve_imported_builtins(
                command_call.name,
                command_call.namespace,
                workspace_index,
            )
            if len(imported_builtin_matches) == 1:
                builtin_from_import = imported_builtin_matches[0]
            elif len(imported_builtin_matches) > 1:
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='ambiguous',
                            reason='Multiple imported builtin commands match this command name.',
                        ),
                        target_symbol_ids=tuple(
                            overload.symbol_id
                            for builtin in imported_builtin_matches
                            for overload in builtin.overloads
                        ),
                    ),
                    None,
                    None,
                )
        if builtin_from_import is not None:
            return (
                ResolutionResult(
                    reference=reference,
                    uncertainty=AnalysisUncertainty(
                        state='resolved',
                        reason=(
                            'Resolved via a static namespace import to bundled '
                            f'{builtin_from_import.package} metadata.'
                        ),
                    ),
                    target_symbol_ids=tuple(
                        overload.symbol_id for overload in builtin_from_import.overloads
                    ),
                ),
                HoverInfo(
                    span=command_call.name_span,
                    contents=_builtin_hover(builtin_from_import),
                ),
                builtin_from_import,
            )
        if not matches:
            implicit_test_builtins = self._resolve_implicit_test_builtins(command_call)
            if len(implicit_test_builtins) == 1:
                builtin = implicit_test_builtins[0]
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='resolved',
                            reason='Resolved via implicit tcltest imports for a test file.',
                        ),
                        target_symbol_ids=tuple(
                            overload.symbol_id for overload in builtin.overloads
                        ),
                    ),
                    HoverInfo(
                        span=command_call.name_span,
                        contents=_builtin_hover(builtin),
                    ),
                    builtin,
                )
            if len(implicit_test_builtins) > 1:
                return (
                    ResolutionResult(
                        reference=reference,
                        uncertainty=AnalysisUncertainty(
                            state='ambiguous',
                            reason='Multiple implicit tcltest builtin commands match this name.',
                        ),
                        target_symbol_ids=tuple(
                            overload.symbol_id
                            for builtin in implicit_test_builtins
                            for overload in builtin.overloads
                        ),
                    ),
                    None,
                    None,
                )

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
                        reason=(
                            'Resolved via a static namespace import.'
                            if resolved_via_import
                            else 'Resolved to a unique procedure definition.'
                        ),
                    ),
                    target_symbol_ids=(proc.symbol_id,),
                ),
                HoverInfo(span=command_call.name_span, contents=detail),
                proc,
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
            embedded_language=None,
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

    def _resolve_imported_builtins(
        self,
        raw_name: str,
        namespace: str,
        workspace_index: WorkspaceIndex,
    ) -> tuple[BuiltinCommand, ...]:
        matches: dict[str, BuiltinCommand] = {}
        for target_name in workspace_index.imported_command_candidates(raw_name, namespace):
            normalized_target_name = _normalize_command_name(target_name)
            for builtin in builtin_commands_any(normalized_target_name):
                matches.setdefault(f'{builtin.package}:{builtin.name}', builtin)
        return tuple(matches.values())

    def _resolve_implicit_test_builtins(
        self,
        command_call: CommandCall,
    ) -> tuple[BuiltinCommand, ...]:
        if not _is_implicit_tcltest_file(command_call.uri):
            return ()
        if command_call.name is None or '::' in command_call.name:
            return ()

        return builtin_commands_any(f'tcltest::{_normalize_command_name(command_call.name)}')


def _metadata_var_binding(
    command_call: CommandCall,
    argument_text: str,
    span: Span,
    kind: BindingKind,
    symbol_ids_by_key: dict[tuple[str, str], str],
) -> VarBinding | None:
    variable_name = _metadata_variable_name(argument_text)
    if variable_name is None:
        return None

    key = (command_call.scope_id, variable_name)
    symbol_id = symbol_ids_by_key.setdefault(
        key,
        variable_symbol_id(command_call.uri, command_call.scope_id, variable_name),
    )
    return VarBinding(
        symbol_id=symbol_id,
        uri=command_call.uri,
        name=variable_name,
        scope_id=command_call.scope_id,
        namespace=command_call.namespace,
        procedure_symbol_id=command_call.procedure_symbol_id,
        kind=kind,
        span=span,
    )


@lru_cache(maxsize=1)
def _annotated_metadata_commands() -> dict[tuple[str, str], MetadataCommand]:
    commands_by_key: dict[tuple[str, str], MetadataCommand] = {}
    for metadata_command in all_metadata_commands():
        if metadata_command.context_name is not None:
            continue
        if not any(
            isinstance(annotation, MetadataBind) for annotation in metadata_command.annotations
        ):
            continue

        key = (metadata_command.metadata_path.name, metadata_command.name)
        existing = commands_by_key.get(key)
        if existing is not None and (
            existing.options != metadata_command.options
            or existing.annotations != metadata_command.annotations
        ):
            raise RuntimeError(
                f'Conflicting metadata binding annotations for `{metadata_command.name}` in '
                f'`{metadata_command.metadata_path.name}`.'
            )
        commands_by_key[key] = metadata_command
    return commands_by_key


def _metadata_command_for_target(target: ResolvedCommandTarget) -> MetadataCommand | None:
    if isinstance(target, BuiltinCommand):
        return _annotated_metadata_commands().get((target.metadata_path_name, target.name))

    source_path = source_id_to_path(target.uri)
    if source_path is None:
        return None
    return _annotated_metadata_commands().get(
        (source_path.name, _normalize_command_name(target.qualified_name))
    )


def _metadata_binding_kind(
    metadata_command: MetadataCommand,
    annotation: MetadataBind,
) -> BindingKind:
    if annotation.kind is not None:
        return annotation.kind

    inferred_kind = name_tail(metadata_command.name.rsplit(' ', 1)[-1])
    if inferred_kind not in BINDING_KINDS:
        raise RuntimeError(
            f'Metadata command `{metadata_command.name}` requires an explicit binding kind.'
        )
    return inferred_kind


def _metadata_variable_name(name: str) -> str | None:
    while name.endswith(':') and not name.endswith('::'):
        name = name[:-1]

    open_paren = name.find('(')
    if open_paren > 0 and name.endswith(')'):
        base_name = name[:open_paren]
        if is_simple_name(base_name):
            name = base_name

    if not is_simple_name(name):
        return None
    return name


def _proc_detail(proc: ProcDecl) -> str:
    parameters = ', '.join(parameter.name for parameter in proc.parameters)
    return f'proc {proc.qualified_name}({parameters})'


def _proc_hover(proc: ProcDecl) -> str:
    detail = _proc_detail(proc)
    if proc.documentation is None:
        return detail
    return f'{detail}\n\n{proc.documentation}'


def _builtin_hover(builtin: BuiltinCommand) -> str:
    if len(builtin.overloads) == 1:
        overload = builtin.overloads[0]
        return f'builtin command {_builtin_signature_heading(overload.signature)}\n\n{overload.documentation}'

    sections = [
        f'`{overload.signature}`\n{overload.documentation}' for overload in builtin.overloads
    ]
    return f'builtin command {builtin.name}\n\n' + '\n\n'.join(sections)


def _builtin_signature_heading(signature: str) -> str:
    return signature.removesuffix(' {}')


def _builtin_resolution_reason(builtin: BuiltinCommand) -> str:
    if builtin.package == 'Tcl':
        return 'Resolved to bundled Tcl metadata.'
    return f'Resolved to bundled {builtin.package} metadata.'


def _normalize_command_name(name: str) -> str:
    return name[2:] if name.startswith('::') else name


def _is_implicit_tcltest_file(uri: str) -> bool:
    return uri.endswith('.test') or uri.endswith('.test.tcl')


def _matching_required_package(
    command_name: str,
    required_packages: frozenset[str],
) -> str | None:
    normalized_name = _normalize_command_name(command_name)
    for package_name in sorted(required_packages):
        if normalized_name == package_name or normalized_name.startswith(f'{package_name}::'):
            return package_name
    return None
