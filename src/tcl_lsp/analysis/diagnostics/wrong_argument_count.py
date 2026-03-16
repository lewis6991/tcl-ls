from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.model import CommandArity, CommandCall, ProcDecl
from tcl_lsp.common import Diagnostic

from .base import (
    AnalysisDiagnosticSeverity,
    DiagnosticChecker,
    DiagnosticContext,
    ResolvedCommandTarget,
)
from .helpers import resolved_command_calls


class WrongArgumentCountChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'wrong-argument-count'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, command_target in resolved_command_calls(context):
            message = _command_argument_message(command_call, command_target)
            if message is None:
                continue
            yield self.emit(span=command_call.span, message=message)


def _command_argument_message(
    command_call: CommandCall,
    command_target: ResolvedCommandTarget,
) -> str | None:
    if command_call.has_expanded_args:
        return None

    arg_count = len(command_call.arg_texts)
    command_name = command_call.name or '<dynamic>'

    if isinstance(command_target, ProcDecl):
        if command_target.arity is None or command_target.arity.accepts(arg_count):
            return None
        expected = _arity_descriptions((command_target.arity,))
    else:
        if not command_target.overloads:
            return None

        supported_arities: list[CommandArity] = []
        for overload in command_target.overloads:
            if overload.arity is None:
                return None
            supported_arities.append(overload.arity)

        if any(arity.accepts(arg_count) for arity in supported_arities):
            return None
        expected = _arity_descriptions(tuple(supported_arities))

    return (
        f'Wrong number of arguments for command `{command_name}`; '
        f'expected {expected}, got {arg_count}.'
    )


def _arity_descriptions(arities: tuple[CommandArity, ...]) -> str:
    unique_descriptions: dict[str, None] = {}
    sorted_arities = sorted(
        arities,
        key=lambda arity: (
            arity.min_args,
            arity.max_args is None,
            -1 if arity.max_args is None else arity.max_args,
        ),
    )
    for arity in sorted_arities:
        unique_descriptions.setdefault(_arity_description(arity), None)

    descriptions = tuple(unique_descriptions)
    if len(descriptions) == 1:
        return descriptions[0]
    if len(descriptions) == 2:
        return f'{descriptions[0]} or {descriptions[1]}'
    return ', '.join(descriptions[:-1]) + f', or {descriptions[-1]}'


def _arity_description(arity: CommandArity) -> str:
    min_args = arity.min_args
    max_args = arity.max_args
    if max_args is None:
        return f'at least {min_args}'
    if min_args == max_args:
        return str(min_args)
    return f'{min_args}..{max_args}'
