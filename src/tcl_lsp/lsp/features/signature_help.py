from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lsprotocol import types

from tcl_lsp.analysis import FactExtractor
from tcl_lsp.analysis.builtins import BuiltinOverload, builtin_commands_by_package
from tcl_lsp.analysis.model import (
    CommandArity,
    CommandCall,
    DocumentFacts,
    ProcDecl,
    ResolutionResult,
)
from tcl_lsp.common import offset_at_position
from tcl_lsp.lsp.state import ManagedDocument
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.parser import Parser


@dataclass(frozen=True, slots=True)
class _SignatureCandidate:
    info: types.SignatureInformation
    arity: CommandArity | None
    parameter_count: int | None


def signature_help(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    metadata_registry: MetadataRegistry,
    parser: Parser,
    extractor: FactExtractor,
    uri: str,
    line: int,
    character: int,
) -> types.SignatureHelp | None:
    document = documents_by_uri.get(uri)
    if document is None:
        return None

    offset = offset_at_position(document.text, line, character)
    if offset is None:
        return None

    prefix_text = document.text[:offset]
    prefix_facts = _prefix_facts(
        parser=parser,
        extractor=extractor,
        uri=uri,
        text=prefix_text,
    )
    if _variable_context(prefix_text, prefix_facts):
        return None

    command_call = _last_attached_command_call(prefix_text, prefix_facts)
    if command_call is None or command_call.name is None:
        return None

    resolution = _resolution_for_call(document, command_call)
    if resolution is None or not resolution.target_symbol_ids:
        return None

    candidates = _signature_candidates_for_symbols(
        documents_by_uri,
        metadata_registry=metadata_registry,
        symbol_ids=resolution.target_symbol_ids,
    )
    if not candidates:
        return None

    active_signature = _active_signature_index(
        candidates,
        argument_count=len(command_call.arg_spans),
    )
    active_parameter = _active_parameter_index(
        candidates[active_signature],
        active_argument=_active_argument_index(prefix_text, command_call),
    )
    return types.SignatureHelp(
        signatures=[candidate.info for candidate in candidates],
        active_signature=active_signature,
        active_parameter=active_parameter,
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


def _variable_context(prefix_text: str, prefix_facts: DocumentFacts) -> bool:
    if prefix_text.endswith('${') or prefix_text.endswith('$'):
        return True
    return any(
        variable_reference.span.end.offset == len(prefix_text)
        for variable_reference in prefix_facts.variable_references
    )


def _last_attached_command_call(
    prefix_text: str,
    prefix_facts: DocumentFacts,
) -> CommandCall | None:
    for command_call in reversed(prefix_facts.command_calls):
        tail_text = prefix_text[command_call.span.end.offset :]
        if all(char in {' ', '\t'} for char in tail_text):
            return command_call
    return None


def _resolution_for_call(
    document: ManagedDocument,
    command_call: CommandCall,
) -> ResolutionResult | None:
    for resolution in document.analysis.resolutions:
        if resolution.reference.kind != 'command':
            continue
        if resolution.reference.span.start.offset != command_call.name_span.start.offset:
            continue
        if resolution.reference.span.end.offset != command_call.name_span.end.offset:
            continue
        return resolution
    return None


def _signature_candidates_for_symbols(
    documents_by_uri: Mapping[str, ManagedDocument],
    *,
    metadata_registry: MetadataRegistry,
    symbol_ids: tuple[str, ...],
) -> tuple[_SignatureCandidate, ...]:
    candidates: list[_SignatureCandidate] = []
    procedures_by_symbol = _procedures_by_symbol(documents_by_uri)
    builtin_overloads_by_symbol = _builtin_overloads_by_symbol(metadata_registry)

    for symbol_id in symbol_ids:
        procedure = procedures_by_symbol.get(symbol_id)
        if procedure is not None:
            candidates.append(_procedure_signature_candidate(procedure))
            continue

        builtin_overload = builtin_overloads_by_symbol.get(symbol_id)
        if builtin_overload is not None:
            candidates.append(_builtin_signature_candidate(builtin_overload))

    return tuple(candidates)


def _procedures_by_symbol(
    documents_by_uri: Mapping[str, ManagedDocument],
) -> dict[str, ProcDecl]:
    procedures_by_symbol: dict[str, ProcDecl] = {}
    for document in documents_by_uri.values():
        for procedure in document.facts.procedures:
            procedures_by_symbol[procedure.symbol_id] = procedure
    return procedures_by_symbol


def _builtin_overloads_by_symbol(
    metadata_registry: MetadataRegistry,
) -> dict[str, BuiltinOverload]:
    overloads_by_symbol: dict[str, BuiltinOverload] = {}
    for package_commands in builtin_commands_by_package(
        metadata_registry=metadata_registry
    ).values():
        for builtin in package_commands.values():
            for overload in builtin.overloads:
                overloads_by_symbol[overload.symbol_id] = overload
    return overloads_by_symbol


def _procedure_signature_candidate(procedure: ProcDecl) -> _SignatureCandidate:
    label_parts = [f'proc {procedure.qualified_name}(']
    parameters: list[types.ParameterInformation] = []
    for index, parameter in enumerate(procedure.parameters):
        start = len(''.join(label_parts))
        label_parts.append(parameter.name)
        end = len(''.join(label_parts))
        parameters.append(types.ParameterInformation(label=(start, end)))
        if index != len(procedure.parameters) - 1:
            label_parts.append(', ')
    label_parts.append(')')
    label = ''.join(label_parts)
    return _SignatureCandidate(
        info=types.SignatureInformation(
            label=label,
            documentation=procedure.documentation,
            parameters=parameters,
        ),
        arity=CommandArity(
            min_args=len(procedure.parameters),
            max_args=len(procedure.parameters),
        ),
        parameter_count=len(procedure.parameters),
    )


def _builtin_signature_candidate(overload: BuiltinOverload) -> _SignatureCandidate:
    return _SignatureCandidate(
        info=types.SignatureInformation(
            label=overload.signature,
            documentation=overload.documentation,
        ),
        arity=overload.arity,
        parameter_count=None,
    )


def _active_signature_index(
    candidates: tuple[_SignatureCandidate, ...],
    *,
    argument_count: int,
) -> int:
    for index, candidate in enumerate(candidates):
        if _arity_accepts(candidate.arity, argument_count):
            return index
    return 0


def _arity_accepts(arity: CommandArity | None, argument_count: int) -> bool:
    if arity is None:
        return True
    return arity.accepts(argument_count)


def _active_argument_index(prefix_text: str, command_call: CommandCall) -> int:
    if not command_call.arg_spans:
        return 0
    tail_text = prefix_text[command_call.span.end.offset :]
    if tail_text and all(char in {' ', '\t'} for char in tail_text):
        return len(command_call.arg_spans)
    return len(command_call.arg_spans) - 1


def _active_parameter_index(
    candidate: _SignatureCandidate,
    *,
    active_argument: int,
) -> int | None:
    if candidate.parameter_count is None or candidate.parameter_count <= 0:
        return None
    return min(active_argument, candidate.parameter_count - 1)
