from __future__ import annotations

from typing import Literal, Protocol

from tcl_lsp.analysis.arity import metadata_signature_arity
from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.embedded_languages import ContextualCommand
from tcl_lsp.analysis.metadata_commands import (
    MetadataOption,
    scan_command_options,
)
from tcl_lsp.analysis.model import CommandArity, CommandCall, ProcDecl
from tcl_lsp.analysis.signature_matching import (
    StructuredMatchState,
    display_metadata_signature,
    is_structured_metadata_signature,
    metadata_signature_match_state,
)
from tcl_lsp.common import Span

from .base import CommandCallKey, DiagnosticContext, ResolvedCommandTarget

type OptionIssueState = Literal['unknown-option', 'missing-option-value']


class SharedCommandOverload(Protocol):
    @property
    def options(self) -> tuple[MetadataOption, ...]: ...

    @property
    def subcommands(self) -> tuple[str, ...]: ...


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
    # Tcl's `return` accepts arbitrary option/value pairs plus an optional
    # trailing result, so generic option diagnostics are not sound here.
    if command_call.name == 'return':
        return None

    if isinstance(command_target, ProcDecl):
        return None

    options = command_shared_option_specs(command_target)
    if options is None:
        return None

    scan_result = scan_command_options(command_call.arg_texts, options, command_call.arg_expanded)
    if scan_result.state in {'ok', 'dynamic', 'unstable'}:
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

    subcommands = command_shared_subcommands(command_target)
    if subcommands is None:
        return None

    if not command_call.arg_texts:
        return None
    if command_call.arg_expanded and command_call.arg_expanded[0]:
        return None

    candidate = command_call.arg_texts[0]
    if candidate is None:
        return None
    if _matches_allowed_value(candidate, subcommands):
        return None

    span = command_call.arg_spans[0] if command_call.arg_spans else command_call.span
    return (candidate, span)


def builtin_shared_option_specs(builtin: BuiltinCommand) -> tuple[MetadataOption, ...] | None:
    return _shared_option_specs(builtin.overloads)


def command_shared_option_specs(
    command_target: BuiltinCommand | ContextualCommand,
) -> tuple[MetadataOption, ...] | None:
    if isinstance(command_target, BuiltinCommand):
        return _shared_option_specs(command_target.overloads)
    return _shared_option_specs(command_target.overloads)


def command_shared_subcommands(
    command_target: BuiltinCommand | ContextualCommand,
) -> tuple[str, ...] | None:
    if isinstance(command_target, BuiltinCommand):
        return _shared_subcommands(command_target.overloads)
    return _shared_subcommands(command_target.overloads)


def command_target_arities(
    command_target: BuiltinCommand | ContextualCommand,
) -> tuple[tuple[str, CommandArity], ...] | None:
    if isinstance(command_target, BuiltinCommand):
        arities: list[tuple[str, CommandArity]] = []
        for overload in command_target.overloads:
            if overload.arity is None:
                return None
            arities.append((overload.signature, overload.arity))
        return tuple(arities)

    arities = []
    for overload in command_target.overloads:
        arity = metadata_signature_arity(overload.signature)
        if arity is None:
            return None
        arities.append((overload.signature, arity))
    return tuple(arities)


def command_target_structured_matches(
    command_call: CommandCall,
    command_target: BuiltinCommand | ContextualCommand,
) -> tuple[tuple[str, bool, StructuredMatchState], ...] | None:
    matches: list[tuple[str, bool, StructuredMatchState]] = []
    if isinstance(command_target, BuiltinCommand):
        for overload in command_target.overloads:
            if not is_structured_metadata_signature(overload.match_signature):
                continue
            matches.append(
                (
                    overload.signature,
                    overload.arity.accepts(len(command_call.arg_texts))
                    if overload.arity is not None
                    else False,
                    metadata_signature_match_state(
                        overload.match_signature,
                        arg_texts=command_call.arg_texts,
                        arg_expanded=command_call.arg_expanded,
                        arg_grouped=command_call.arg_grouped,
                    ),
                )
            )
        return tuple(matches) or None

    for overload in command_target.overloads:
        if not is_structured_metadata_signature(overload.signature):
            continue
        arity = metadata_signature_arity(overload.signature)
        display_signature = _display_command_signature(
            command_target.name,
            display_metadata_signature(overload.signature),
        )
        matches.append(
            (
                display_signature,
                arity.accepts(len(command_call.arg_texts)) if arity is not None else False,
                metadata_signature_match_state(
                    overload.signature,
                    arg_texts=command_call.arg_texts,
                    arg_expanded=command_call.arg_expanded,
                    arg_grouped=command_call.arg_grouped,
                ),
            )
        )
    return tuple(matches) or None


def _display_command_signature(command_name: str, signature: str) -> str:
    if not signature or signature == '{}':
        return command_name
    return f'{command_name} {{{signature}}}'


def _shared_option_specs(
    overloads: tuple[SharedCommandOverload, ...],
) -> tuple[MetadataOption, ...] | None:
    if not overloads:
        return None
    if any(not overload.options for overload in overloads):
        return None

    first_options = overloads[0].options
    if any(overload.options != first_options for overload in overloads[1:]):
        return None
    return first_options


def builtin_shared_subcommands(
    builtin: BuiltinCommand,
) -> tuple[str, ...] | None:
    return _shared_subcommands(builtin.overloads)


def _shared_subcommands(overloads: tuple[SharedCommandOverload, ...]) -> tuple[str, ...] | None:
    if not overloads:
        return None

    first_subcommands = overloads[0].subcommands
    if not first_subcommands:
        return None
    if any(overload.subcommands != first_subcommands for overload in overloads[1:]):
        return None
    return first_subcommands


def _matches_allowed_value(candidate: str, allowed_values: tuple[str, ...]) -> bool:
    if candidate in allowed_values:
        return True
    matching_prefixes = tuple(value for value in allowed_values if value.startswith(candidate))
    return len(matching_prefixes) == 1
