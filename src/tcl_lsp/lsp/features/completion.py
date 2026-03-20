from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
from tcl_lsp.analysis.metadata_commands import MetadataOption, scan_command_options
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.analysis.model import CommandCall, DocumentFacts, ProcDecl
from tcl_lsp.common import offset_at_position
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.parser import Parser
from tcl_lsp.project.paths import source_id_to_path

type CompletionKind = Literal['argument', 'command', 'package', 'variable']


@dataclass(frozen=True, slots=True)
class _CompletionContext:
    kind: CompletionKind
    prefix: str
    namespace: str
    scope_id: str | None = None
    command_call: CommandCall | None = None
    argument_index: int | None = None


def completion_items(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    parser: Parser,
    extractor: FactExtractor,
    uri: str,
    line: int,
    character: int,
) -> tuple[types.CompletionItem, ...]:
    document = documents_by_uri.get(uri)
    if document is None:
        return ()

    offset = offset_at_position(document.text, line, character)
    if offset is None:
        return ()

    prefix_text = document.text[:offset]
    prefix_facts = _prefix_facts(
        parser=parser,
        extractor=extractor,
        uri=uri,
        text=prefix_text,
    )
    context = _completion_context(
        document=document,
        prefix_text=prefix_text,
        prefix_facts=prefix_facts,
        line=line,
        character=character,
    )
    if context is None:
        return ()

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
        return _argument_completion_items(
            document=document,
            workspace_index=workspace_index,
            metadata_registry=metadata_registry,
            command_call=context.command_call,
            argument_index=context.argument_index or 0,
            prefix=context.prefix,
        )
    if context.kind == 'package':
        return _package_completion_items(
            documents_by_uri,
            workspace_index=workspace_index,
            metadata_registry=metadata_registry,
            prefix=context.prefix,
        )
    return _variable_completion_items(
        document=document,
        prefix=context.prefix,
        scope_id=context.scope_id,
    )


def _prefix_facts(
    *,
    parser: Parser,
    extractor: FactExtractor,
    uri: str,
    text: str,
) -> DocumentFacts:
    parse_result = parser.parse_document(path=uri, text=text)
    return extractor.extract(
        parse_result,
        include_parse_result=False,
        include_lexical_spans=False,
    )


def _completion_context(
    *,
    document: ManagedDocument,
    prefix_text: str,
    prefix_facts: DocumentFacts,
    line: int,
    character: int,
) -> _CompletionContext | None:
    variable_prefix = _variable_prefix(prefix_text, prefix_facts)
    attached_call = _last_attached_command_call(prefix_text, prefix_facts)
    current_namespace = (
        attached_call.namespace
        if attached_call is not None
        else _namespace_at_position(document.facts, line=line, character=character)
    )

    if variable_prefix is not None:
        return _CompletionContext(
            kind='variable',
            prefix=variable_prefix,
            namespace=current_namespace,
            scope_id=attached_call.scope_id if attached_call is not None else None,
        )

    package_prefix = _package_prefix(prefix_text, attached_call)
    if package_prefix is not None:
        return _CompletionContext(
            kind='package',
            prefix=package_prefix,
            namespace=current_namespace,
        )

    if attached_call is not None and attached_call.name_span.end.offset == len(prefix_text):
        return _CompletionContext(
            kind='command',
            prefix=attached_call.name or '',
            namespace=attached_call.namespace,
        )

    argument_context = _argument_context(prefix_text, attached_call)
    if argument_context is not None and attached_call is not None:
        argument_prefix, argument_index = argument_context
        return _CompletionContext(
            kind='argument',
            prefix=argument_prefix,
            namespace=attached_call.namespace,
            command_call=attached_call,
            argument_index=argument_index,
        )

    if _is_empty_command_position(prefix_text):
        return _CompletionContext(
            kind='command',
            prefix='',
            namespace=current_namespace,
        )

    return None


def _variable_prefix(prefix_text: str, prefix_facts: DocumentFacts) -> str | None:
    if prefix_text.endswith('${') or prefix_text.endswith('$'):
        return ''

    for variable_reference in reversed(prefix_facts.variable_references):
        if variable_reference.span.end.offset == len(prefix_text):
            return variable_reference.name

    open_brace_index = prefix_text.rfind('${')
    if open_brace_index >= 0 and '}' not in prefix_text[open_brace_index + 2 :]:
        return prefix_text[open_brace_index + 2 :]

    return None


def _package_prefix(prefix_text: str, attached_call: CommandCall | None) -> str | None:
    if attached_call is None or attached_call.name != 'package require':
        return None

    if not attached_call.arg_spans:
        return ''

    last_arg_span = attached_call.arg_spans[-1]
    if last_arg_span.end.offset == len(prefix_text):
        argument_text = attached_call.arg_texts[-1]
        return '' if argument_text is None else argument_text
    return ''


def _last_attached_command_call(
    prefix_text: str,
    prefix_facts: DocumentFacts,
) -> CommandCall | None:
    for command_call in reversed(prefix_facts.command_calls):
        tail_text = prefix_text[command_call.span.end.offset :]
        if all(char in {' ', '\t'} for char in tail_text):
            return command_call
    return None


def _argument_context(
    prefix_text: str,
    attached_call: CommandCall | None,
) -> tuple[str, int] | None:
    if attached_call is None:
        return None

    if attached_call.arg_spans and attached_call.arg_spans[-1].end.offset == len(prefix_text):
        argument_text = attached_call.arg_texts[-1]
        return ('' if argument_text is None else argument_text, len(attached_call.arg_spans) - 1)

    tail_text = prefix_text[attached_call.span.end.offset :]
    if tail_text and all(char in {' ', '\t'} for char in tail_text):
        return ('', len(attached_call.arg_spans))

    return None


def _namespace_at_position(facts: DocumentFacts, *, line: int, character: int) -> str:
    matches = [
        namespace
        for namespace in facts.namespaces
        if namespace.span.contains(line=line, character=character)
    ]
    if not matches:
        return '::'
    return min(
        matches,
        key=lambda namespace: namespace.span.end.offset - namespace.span.start.offset,
    ).qualified_name


def _is_empty_command_position(prefix_text: str) -> bool:
    index = len(prefix_text) - 1
    while index >= 0 and prefix_text[index] in {' ', '\t'}:
        index -= 1
    if index < 0:
        return True
    return prefix_text[index] in {'\n', ';', '['}


def _command_completion_items(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    document: ManagedDocument,
    workspace_index: WorkspaceIndex,
    metadata_registry: MetadataRegistry,
    prefix: str,
    current_namespace: str,
) -> tuple[types.CompletionItem, ...]:
    items: list[types.CompletionItem] = []
    seen: set[tuple[str, str | None]] = set()

    for procedure in _iter_procedures(documents_by_uri):
        label = _command_label(procedure.qualified_name, current_namespace=current_namespace)
        if not _command_matches_prefix(procedure, label=label, prefix=prefix):
            continue
        key = (label, procedure.qualified_name)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            types.CompletionItem(
                label=label,
                insert_text=label,
                kind=types.CompletionItemKind.Function,
                detail=_proc_completion_detail(procedure),
                documentation=procedure.documentation,
                sort_text=_command_sort_text(
                    label,
                    rank=_procedure_completion_rank(
                        procedure.qualified_name,
                        current_namespace=current_namespace,
                    ),
                ),
            )
        )

    for command_import in document.facts.command_imports:
        if command_import.kind != 'exact' or command_import.imported_name is None:
            continue
        if not _matches_prefix(command_import.imported_name, prefix):
            continue
        key = (command_import.imported_name, command_import.target_name)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            types.CompletionItem(
                label=command_import.imported_name,
                insert_text=command_import.imported_name,
                kind=types.CompletionItemKind.Function,
                detail=f'import {command_import.target_name}',
                sort_text=_command_sort_text(command_import.imported_name, rank=1),
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
            if ' ' in builtin.name or not _matches_prefix(builtin.name, prefix):
                continue
            key = (builtin.name, builtin.package)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                types.CompletionItem(
                    label=builtin.name,
                    insert_text=builtin.name,
                    kind=types.CompletionItemKind.Function,
                    detail=_builtin_completion_detail(
                        builtin.name, package_name, builtin.overloads
                    ),
                    documentation=_builtin_completion_documentation(builtin.overloads),
                    sort_text=_command_sort_text(builtin.name, rank=2),
                )
            )

    return tuple(sorted(items, key=lambda item: (item.sort_text or item.label, item.label)))


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

    for _, entries in workspace_index.package_indexes():
        for entry in entries:
            package_candidates.setdefault(entry.name, 'workspace package')

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


def _command_matches_prefix(procedure: ProcDecl, *, label: str, prefix: str) -> bool:
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
