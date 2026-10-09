from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from lsprotocol import types

from tcl_lsp.analysis import FactExtractor, WorkspaceIndex
from tcl_lsp.analysis.builtins import (
    BuiltinCommand,
    BuiltinOverload,
    builtin_command_for_packages,
    builtin_commands_by_package,
    canonical_builtin_package_name,
)
from tcl_lsp.analysis.environments import registry_at_offset
from tcl_lsp.analysis.metadata_commands import MetadataOption, scan_command_options
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.analysis.model import CommandCall, ProcDecl
from tcl_lsp.lsp.features.cursor_context import (
    CursorContext,
    cursor_context,
    is_empty_command_position,
)
from tcl_lsp.lsp.state import ManagedDocument, empty_analysis
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.parser import Parser
from tcl_lsp.project.paths import source_id_to_path

type CompletionKind = Literal['argument', 'command', 'package', 'variable']

_MAX_COMMAND_COMPLETION_ITEMS = 200


@dataclass(frozen=True, slots=True)
class CompletionResults:
    items: tuple[types.CompletionItem, ...]
    is_incomplete: bool = False


@dataclass(frozen=True, slots=True)
class _CompletionContext:
    kind: CompletionKind
    prefix: str
    namespace: str
    scope_id: str | None = None
    command_call: CommandCall | None = None
    argument_index: int | None = None


@dataclass(frozen=True, slots=True)
class _CommandCandidate:
    label: str
    sort_text: str
    procedure: ProcDecl | None = None
    imported_name: str | None = None
    import_target_name: str | None = None
    builtin_name: str | None = None
    builtin_package_name: str | None = None
    builtin_overloads: tuple[BuiltinOverload, ...] = ()


def completion_items(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    parser: Parser | None = None,
    live_text: str | None = None,
    uri: str,
    line: int,
    character: int,
) -> CompletionResults:
    document = documents_by_uri.get(uri)
    if document is None:
        return CompletionResults(items=())

    live_document = live_text is not None and live_text != document.text
    if live_document:
        # Use the same extraction as diagnostics. Mixing live cursor positions
        # with old scopes can select the wrong environment, namespace, or body.
        assert live_text is not None
        live_parser = parser or Parser()
        extractor = FactExtractor(live_parser, metadata_registry=metadata_registry)
        try:
            parse_result = live_parser.parse_document(uri, live_text)
            facts = extractor.extract(
                parse_result,
                include_lexical_spans=False,
                environment_rules=document.facts.environment_rules,
            )
        finally:
            extractor.close()
        document = replace(
            document,
            text=live_text,
            parse_result=parse_result,
            facts=facts,
            analysis=empty_analysis(uri, facts.document_symbols),
            lexical_spans_included=False,
        )
        documents_by_uri = {**documents_by_uri, uri: document}
        workspace_index = workspace_index.clone()
        workspace_index.update(uri, facts)

    context = cursor_context(document, line=line, character=character)
    if context is None:
        return CompletionResults(items=())
    # A call uses its entry environment, even with the cursor at its end.
    metadata_offset = (
        context.attached_command_call.name_span.start.offset
        if context.attached_command_call is not None
        else context.offset
    )
    metadata_registry = registry_at_offset(
        metadata_registry, document.facts.environment_scopes, metadata_offset
    )
    context = _completion_context(
        document=document,
        cursor=context,
    )
    if context is None:
        return CompletionResults(items=())

    return _completion_results_for_context(
        documents_by_uri,
        document=document,
        workspace_index=workspace_index,
        metadata_registry=metadata_registry,
        context=context,
    )


def _completion_results_for_context(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    document: ManagedDocument,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    context: _CompletionContext,
) -> CompletionResults:
    if context.kind == 'command':
        return _command_completion_items(
            documents_by_uri,
            document=document,
            workspace_index=workspace_index,
            metadata_registry=metadata_registry,
            prefix=context.prefix,
            current_namespace=context.namespace,
        )
    if context.kind == 'argument' and context.command_call is not None:
        return CompletionResults(
            items=_argument_completion_items(
                document=document,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
                command_call=context.command_call,
                argument_index=context.argument_index or 0,
                prefix=context.prefix,
            )
        )
    if context.kind == 'package':
        return CompletionResults(
            items=_package_completion_items(
                documents_by_uri,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
                prefix=context.prefix,
            )
        )
    return CompletionResults(
        items=_variable_completion_items(
            document=document,
            prefix=context.prefix,
            scope_id=context.scope_id,
        )
    )


def _completion_context(
    *,
    document: ManagedDocument,
    cursor: CursorContext,
) -> _CompletionContext | None:
    if cursor.variable_prefix is not None:
        return _CompletionContext(
            kind='variable',
            prefix=cursor.variable_prefix,
            namespace=cursor.namespace,
            scope_id=cursor.scope_id,
        )

    attached_call = cursor.attached_command_call
    if attached_call is not None and attached_call.name == 'package require':
        return _CompletionContext(
            kind='package',
            prefix='' if cursor.argument_prefix is None else cursor.argument_prefix,
            namespace=cursor.namespace,
        )

    if cursor.command_name_prefix is not None:
        return _CompletionContext(
            kind='command',
            prefix=cursor.command_name_prefix,
            namespace=cursor.namespace,
        )

    if attached_call is not None and cursor.argument_prefix is not None:
        return _CompletionContext(
            kind='argument',
            prefix=cursor.argument_prefix,
            namespace=cursor.namespace,
            command_call=attached_call,
            argument_index=0 if cursor.argument_index is None else cursor.argument_index,
        )

    if is_empty_command_position(document.text, offset=cursor.offset):
        return _CompletionContext(
            kind='command',
            prefix='',
            namespace=cursor.namespace,
        )

    return None


def _command_completion_items(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    document: ManagedDocument,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    prefix: str,
    current_namespace: str,
) -> CompletionResults:
    absolute_prefix = prefix.startswith('::')
    candidates: list[_CommandCandidate] = []
    seen: set[tuple[str, str | None]] = set()

    for procedure in _iter_procedures(documents_by_uri):
        label = _command_completion_label(
            procedure.qualified_name,
            current_namespace=current_namespace,
            absolute_prefix=absolute_prefix,
        )
        if not _command_matches_prefix(
            procedure,
            label=label,
            prefix=prefix,
            absolute_prefix=absolute_prefix,
        ):
            continue
        key = (label, procedure.qualified_name)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            _CommandCandidate(
                label=label,
                sort_text=_command_sort_text(
                    label,
                    rank=_procedure_completion_rank(
                        procedure.qualified_name,
                        current_namespace=current_namespace,
                    ),
                ),
                procedure=procedure,
            )
        )

    for command_import in document.facts.command_imports:
        if absolute_prefix:
            continue
        if command_import.kind != 'exact' or command_import.imported_name is None:
            continue
        if not _matches_prefix(command_import.imported_name, prefix):
            continue
        key = (command_import.imported_name, command_import.target_name)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            _CommandCandidate(
                label=command_import.imported_name,
                sort_text=_command_sort_text(command_import.imported_name, rank=1),
                imported_name=command_import.imported_name,
                import_target_name=command_import.target_name,
            )
        )

    builtin_packages = _builtin_completion_packages(
        document=document,
        workspace_index=workspace_index,
        metadata_registry=metadata_registry,
    )
    for package_name in builtin_packages:
        for builtin in (
            builtin_commands_by_package(metadata_registry=metadata_registry)
            .get(package_name, {})
            .values()
        ):
            label = _builtin_completion_label(builtin.name, absolute_prefix=absolute_prefix)
            if ' ' in builtin.name or not _matches_prefix(label, prefix):
                continue
            key = (label, builtin.package)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                _CommandCandidate(
                    label=label,
                    sort_text=_command_sort_text(label, rank=2),
                    builtin_name=builtin.name,
                    builtin_package_name=package_name,
                    builtin_overloads=builtin.overloads,
                )
            )

    incomplete = len(candidates) > _MAX_COMMAND_COMPLETION_ITEMS
    if incomplete:
        selected_candidates = heapq.nsmallest(
            _MAX_COMMAND_COMPLETION_ITEMS,
            candidates,
            key=_command_candidate_sort_key,
        )
    else:
        selected_candidates = sorted(candidates, key=_command_candidate_sort_key)

    return CompletionResults(
        items=tuple(_command_completion_item(candidate) for candidate in selected_candidates),
        is_incomplete=incomplete,
    )


def _argument_completion_items(
    *,
    document: ManagedDocument,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    command_call: CommandCall,
    argument_index: int,
    prefix: str,
) -> tuple[types.CompletionItem, ...]:
    if command_call.name is None:
        return ()

    builtin = builtin_command_for_packages(
        command_call.name,
        frozenset(
            _builtin_completion_packages(
                document=document,
                workspace_index=workspace_index,
                metadata_registry=metadata_registry,
            )
        ),
        metadata_registry=metadata_registry,
    )
    if builtin is None:
        return ()

    items: list[types.CompletionItem] = []
    items.extend(
        _subcommand_completion_items(
            builtin=builtin,
            metadata_registry=metadata_registry,
            argument_index=argument_index,
            prefix=prefix,
        )
    )
    items.extend(
        _option_completion_items(
            command_call=command_call,
            builtin=builtin,
            argument_index=argument_index,
            prefix=prefix,
        )
    )
    return tuple(sorted(items, key=lambda item: (item.sort_text or item.label, item.label)))


def _package_completion_items(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    prefix: str,
) -> tuple[types.CompletionItem, ...]:
    package_candidates: dict[str, str] = {}

    for package_name in builtin_commands_by_package(metadata_registry=metadata_registry):
        if package_name == 'Tcl':
            continue
        package_candidates.setdefault(package_name, 'bundled metadata package')

    for document in documents_by_uri.values():
        for package in document.facts.package_provides:
            package_candidates[package.name] = 'workspace package'

    for package_name in workspace_index.package_index_names():
        package_candidates.setdefault(package_name, 'workspace package')

    items = [
        types.CompletionItem(
            label=package_name,
            insert_text=package_name,
            kind=types.CompletionItemKind.Module,
            detail=detail,
            sort_text=package_name.casefold(),
        )
        for package_name, detail in package_candidates.items()
        if _matches_prefix(package_name, prefix)
    ]
    return tuple(sorted(items, key=lambda item: (item.sort_text or item.label, item.label)))


def _variable_completion_items(
    *,
    document: ManagedDocument,
    prefix: str,
    scope_id: str | None,
) -> tuple[types.CompletionItem, ...]:
    if scope_id is None:
        return ()

    seen: set[str] = set()
    items: list[types.CompletionItem] = []
    for binding in sorted(
        document.facts.variable_bindings, key=lambda item: item.span.start.offset
    ):
        if binding.scope_id != scope_id or not _matches_prefix(binding.name, prefix):
            continue
        if binding.name in seen:
            continue
        seen.add(binding.name)
        items.append(
            types.CompletionItem(
                label=binding.name,
                insert_text=binding.name,
                kind=types.CompletionItemKind.Variable,
                detail=f'{binding.kind} {binding.name}',
                sort_text=binding.name.casefold(),
            )
        )

    return tuple(items)


def _subcommand_completion_items(
    *,
    builtin: BuiltinCommand,
    metadata_registry: MetadataRegistry,
    argument_index: int,
    prefix: str,
) -> tuple[types.CompletionItem, ...]:
    if argument_index != 0:
        return ()

    subcommands = _builtin_shared_subcommands(builtin)
    if subcommands is None:
        return ()

    items: list[types.CompletionItem] = []
    for subcommand in subcommands:
        if not _matches_prefix(subcommand, prefix):
            continue

        nested_name = f'{builtin.name} {subcommand}'
        nested_builtin = builtin_command_for_packages(
            nested_name,
            frozenset({builtin.package}),
            metadata_registry=metadata_registry,
        )
        detail = f'subcommand of {builtin.name}'
        documentation = None
        if nested_builtin is not None:
            detail = _builtin_completion_detail(
                nested_builtin.name,
                nested_builtin.package,
                nested_builtin.overloads,
            )
            documentation = _builtin_completion_documentation(nested_builtin.overloads)

        items.append(
            types.CompletionItem(
                label=subcommand,
                insert_text=subcommand,
                kind=types.CompletionItemKind.Function,
                detail=detail,
                documentation=documentation,
                sort_text=_command_sort_text(subcommand, rank=0),
            )
        )
    return tuple(items)


def _option_completion_items(
    *,
    command_call: CommandCall,
    builtin: BuiltinCommand,
    argument_index: int,
    prefix: str,
) -> tuple[types.CompletionItem, ...]:
    if command_call.name == 'return':
        return ()

    options = _builtin_shared_option_specs(builtin)
    if options is None:
        return ()
    if prefix and not prefix.startswith('-'):
        return ()
    if not _option_phase_active(
        command_call.arg_texts[:argument_index],
        options,
        command_call.arg_expanded[:argument_index],
    ):
        return ()

    items: list[types.CompletionItem] = []
    for option in options:
        if not _matches_prefix(option.name, prefix):
            continue
        items.append(
            types.CompletionItem(
                label=option.name,
                insert_text=option.name,
                kind=types.CompletionItemKind.Keyword,
                detail=_option_completion_detail(builtin.name, option),
                sort_text=_command_sort_text(option.name, rank=1),
            )
        )
    return tuple(items)


def _builtin_completion_packages(
    *,
    document: ManagedDocument,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
) -> tuple[str, ...]:
    packages: dict[str, None] = {'Tcl': None}
    source_path = source_id_to_path(document.uri)
    if source_path is None:
        required_packages = frozenset(
            package_require.name for package_require in document.facts.package_requires
        )
    else:
        required_packages = dependency_required_packages(
            source_path,
            document.facts,
            workspace_index,
            metadata_registry=metadata_registry,
        )

    if _is_implicit_tcltest_file(document.uri):
        required_packages = required_packages | frozenset({'tcltest'})

    for package_name in sorted(required_packages):
        packages.setdefault(canonical_builtin_package_name(package_name), None)

    return tuple(packages)


def _iter_procedures(
    documents_by_uri: Mapping[str, ManagedDocument],
) -> tuple[ProcDecl, ...]:
    latest_by_symbol: dict[str, ProcDecl] = {}
    for document in documents_by_uri.values():
        for procedure in document.facts.procedures:
            latest_by_symbol[procedure.symbol_id] = procedure
    return tuple(latest_by_symbol.values())


def _command_completion_label(
    qualified_name: str,
    *,
    current_namespace: str,
    absolute_prefix: bool,
) -> str:
    if absolute_prefix:
        return qualified_name
    return _command_label(qualified_name, current_namespace=current_namespace)


def _command_label(qualified_name: str, *, current_namespace: str) -> str:
    if qualified_name == '::':
        return '::'

    normalized_name = qualified_name.removeprefix('::')
    if current_namespace == '::':
        return normalized_name

    current_prefix = current_namespace.removeprefix('::') + '::'
    if normalized_name.startswith(current_prefix):
        relative_name = normalized_name[len(current_prefix) :]
        if '::' not in relative_name:
            return relative_name

    return normalized_name


def _builtin_completion_label(name: str, *, absolute_prefix: bool) -> str:
    if absolute_prefix:
        return f'::{name}'
    return name


def _command_matches_prefix(
    procedure: ProcDecl,
    *,
    label: str,
    prefix: str,
    absolute_prefix: bool,
) -> bool:
    if absolute_prefix:
        return procedure.qualified_name.startswith(prefix)
    normalized_name = procedure.qualified_name.removeprefix('::')
    return (
        _matches_prefix(label, prefix)
        or _matches_prefix(normalized_name, prefix)
        or _matches_prefix(procedure.name, prefix)
    )


def _matches_prefix(value: str, prefix: str) -> bool:
    if not prefix:
        return True
    return value.startswith(prefix)


def _procedure_completion_rank(qualified_name: str, *, current_namespace: str) -> int:
    if current_namespace != '::':
        current_prefix = current_namespace + '::'
        if qualified_name.startswith(current_prefix):
            return 0
    if '::' not in qualified_name.removeprefix('::'):
        return 0
    return 1


def _proc_completion_detail(procedure: ProcDecl) -> str:
    parameter_names = ', '.join(parameter.name for parameter in procedure.parameters)
    return f'proc {procedure.qualified_name}({parameter_names})'


def _builtin_completion_detail(
    name: str,
    package_name: str,
    overloads: tuple[BuiltinOverload, ...],
) -> str:
    if len(overloads) == 1:
        overload = overloads[0]
        return f'{package_name}: {overload.signature}'
    if len(overloads) > 1:
        return f'{package_name}: {name} ({len(overloads)} overloads)'
    return package_name


def _builtin_completion_documentation(overloads: tuple[BuiltinOverload, ...]) -> str | None:
    if len(overloads) != 1:
        return None
    return overloads[0].documentation


def _command_sort_text(label: str, *, rank: int) -> str:
    return f'{rank}:{label.casefold()}'


def _command_candidate_sort_key(candidate: _CommandCandidate) -> tuple[str, str]:
    return (candidate.sort_text, candidate.label)


def _command_completion_item(candidate: _CommandCandidate) -> types.CompletionItem:
    if candidate.procedure is not None:
        return types.CompletionItem(
            label=candidate.label,
            insert_text=candidate.label,
            kind=types.CompletionItemKind.Function,
            detail=_proc_completion_detail(candidate.procedure),
            documentation=candidate.procedure.documentation,
            sort_text=candidate.sort_text,
        )

    if candidate.imported_name is not None and candidate.import_target_name is not None:
        return types.CompletionItem(
            label=candidate.label,
            insert_text=candidate.label,
            kind=types.CompletionItemKind.Function,
            detail=f'import {candidate.import_target_name}',
            sort_text=candidate.sort_text,
        )

    assert candidate.builtin_name is not None
    assert candidate.builtin_package_name is not None
    return types.CompletionItem(
        label=candidate.label,
        insert_text=candidate.label,
        kind=types.CompletionItemKind.Function,
        detail=_builtin_completion_detail(
            candidate.builtin_name,
            candidate.builtin_package_name,
            candidate.builtin_overloads,
        ),
        documentation=_builtin_completion_documentation(candidate.builtin_overloads),
        sort_text=candidate.sort_text,
    )


def _builtin_shared_option_specs(builtin: BuiltinCommand) -> tuple[MetadataOption, ...] | None:
    if not builtin.overloads:
        return None
    if any(not overload.options for overload in builtin.overloads):
        return None

    first_options = builtin.overloads[0].options
    if any(overload.options != first_options for overload in builtin.overloads[1:]):
        return None
    return first_options


def _builtin_shared_subcommands(
    builtin: BuiltinCommand,
) -> tuple[str, ...] | None:
    if not builtin.overloads:
        return None

    first_subcommands = builtin.overloads[0].subcommands
    if not first_subcommands:
        return None
    if any(overload.subcommands != first_subcommands for overload in builtin.overloads[1:]):
        return None
    return first_subcommands


def _option_phase_active(
    previous_arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    previous_arg_expanded: tuple[bool, ...],
) -> bool:
    if not previous_arg_texts:
        return True

    scan_result = scan_command_options(previous_arg_texts, options, previous_arg_expanded)
    if scan_result.state != 'ok':
        return False
    if scan_result.positional_indices:
        return False
    return '--' not in previous_arg_texts


def _option_completion_detail(command_name: str, option: MetadataOption) -> str:
    if option.kind == 'value':
        return f'option for {command_name} (requires value)'
    if option.kind == 'stop':
        return f'option terminator for {command_name}'
    return f'option for {command_name}'


def _is_implicit_tcltest_file(uri: str) -> bool:
    return uri.endswith('.test') or uri.endswith('.test.tcl')
