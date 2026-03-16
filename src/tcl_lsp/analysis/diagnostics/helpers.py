from __future__ import annotations

from typing import Literal

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.metadata_commands import MetadataOption, scan_command_options
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
    def builtin_option_specs(builtin: BuiltinCommand) -> tuple[MetadataOption, ...] | None:
        if not builtin.overloads:
            return None
        if any(not overload.options for overload in builtin.overloads):
            return None

        first_options = builtin.overloads[0].options
        if any(overload.options != first_options for overload in builtin.overloads[1:]):
            return None
        return first_options

    if isinstance(command_target, ProcDecl):
        return None

    options = builtin_option_specs(command_target)
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
