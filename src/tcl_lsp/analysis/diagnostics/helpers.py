from __future__ import annotations

from typing import Literal

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.metadata_commands import (
    MetadataOption,
    MetadataValueSet,
    scan_command_options,
    select_argument_indices,
)
from tcl_lsp.analysis.model import CommandCall, ProcDecl
from tcl_lsp.common import Span

from .base import CommandCallKey, DiagnosticContext, ResolvedCommandTarget

type OptionIssueState = Literal['unknown-option', 'missing-option-value']


def command_call_key(command_call: CommandCall) -> CommandCallKey:
    return (
        command_call.uri,
        command_call.span.start.offset,
        command_call.span.end.offset,
        command_call.name_span.start.offset,
        command_call.name_span.end.offset,
    )


def resolved_command_calls(
    context: DiagnosticContext,
) -> tuple[tuple[CommandCall, ResolvedCommandTarget], ...]:
    def command_call_specificity(command_call: CommandCall) -> tuple[int, int]:
        static_segments = 0 if command_call.name is None else command_call.name.count(' ') + 1
        return (
            static_segments,
            command_call.name_span.end.offset - command_call.name_span.start.offset,
        )

    most_specific_by_span: dict[tuple[str, int, int], CommandCall] = {}
    for command_call in context.facts.command_calls:
        key = (
            command_call.uri,
            command_call.span.start.offset,
            command_call.span.end.offset,
        )
        current = most_specific_by_span.get(key)
        if current is None or command_call_specificity(command_call) > command_call_specificity(
            current
        ):
            most_specific_by_span[key] = command_call

    resolved: list[tuple[CommandCall, ResolvedCommandTarget]] = []
    for command_call in sorted(
        most_specific_by_span.values(),
        key=lambda command_call: command_call.span.start.offset,
    ):
        command_target = context.command_targets.get(command_call_key(command_call))
        if command_target is None:
            continue
        resolved.append((command_call, command_target))
    return tuple(resolved)


def command_option_issue(
    command_call: CommandCall,
    command_target: ResolvedCommandTarget,
) -> tuple[OptionIssueState, str, Span] | None:
    if isinstance(command_target, ProcDecl):
        return None

    options = builtin_shared_option_specs(command_target)
    if options is None:
        return None

    scan_result = scan_command_options(command_call.arg_texts, options)
    if scan_result.state in {'ok', 'dynamic'}:
        return None

    if scan_result.option_index is None or scan_result.option_name is None:
        return None

    if 0 <= scan_result.option_index < len(command_call.arg_spans):
        span = command_call.arg_spans[scan_result.option_index]
    else:
        span = command_call.span
    if scan_result.state == 'unknown-option':
        return ('unknown-option', scan_result.option_name, span)
    return ('missing-option-value', scan_result.option_name, span)


def command_subcommand_issue(
    command_call: CommandCall,
    command_target: ResolvedCommandTarget,
) -> tuple[str, Span] | None:
    if isinstance(command_target, ProcDecl):
        return None

    shared = builtin_shared_value_sets(command_target)
    if shared is None:
        return None

    value_sets, options = shared
    for value_set in value_sets:
        if value_set.kind != 'subcommand':
            continue

        indices = select_argument_indices(value_set.selector, command_call.arg_texts, options)
        if indices is None or len(indices) != 1:
            continue

        index = indices[0]
        if not 0 <= index < len(command_call.arg_texts):
            continue
        candidate = command_call.arg_texts[index]
        if candidate is None:
            continue
        if _matches_allowed_value(candidate, value_set.values):
            continue

        span = command_call.arg_spans[index] if index < len(command_call.arg_spans) else command_call.span
        return (candidate, span)
    return None


def builtin_shared_option_specs(builtin: BuiltinCommand) -> tuple[MetadataOption, ...] | None:
    if not builtin.overloads:
        return None
    if any(not overload.options for overload in builtin.overloads):
        return None

    first_options = builtin.overloads[0].options
    if any(overload.options != first_options for overload in builtin.overloads[1:]):
        return None
    return first_options


def builtin_shared_value_sets(
    builtin: BuiltinCommand,
) -> tuple[tuple[MetadataValueSet, ...], tuple[MetadataOption, ...]] | None:
    if not builtin.overloads:
        return None

    first_value_sets = builtin.overloads[0].value_sets
    first_options = builtin.overloads[0].options
    if any(
        overload.value_sets != first_value_sets or overload.options != first_options
        for overload in builtin.overloads[1:]
    ):
        return None
    return (first_value_sets, first_options)


def _matches_allowed_value(candidate: str, allowed_values: tuple[str, ...]) -> bool:
    if candidate in allowed_values:
        return True
    matching_prefixes = tuple(value for value in allowed_values if value.startswith(candidate))
    return len(matching_prefixes) == 1
