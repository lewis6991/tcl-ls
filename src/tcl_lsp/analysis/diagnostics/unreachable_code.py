from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import ClassVar, Literal, override

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.control_flow import (
    CatchControlFlowCommand,
    ControlFlowCommand,
    ControlFlowScript,
    ForControlFlowCommand,
    IfControlFlowCommand,
    NamespaceEvalControlFlowCommand,
    ProcControlFlowCommand,
    SwitchControlFlowCommand,
    TryControlFlowCommand,
    WhileControlFlowCommand,
)
from tcl_lsp.analysis.flow.exprs import eval_expr_text
from tcl_lsp.analysis.flow.variables import VariableFlowState
from tcl_lsp.common import Diagnostic, Span

from .base import AnalysisDiagnosticSeverity, CommandCallKey, DiagnosticChecker, DiagnosticContext

type CompletionKind = Literal['normal', 'return', 'break', 'continue', 'error', 'halt']
type DiagnosticEmitter = Callable[[Span], None]

_NORMAL: frozenset[CompletionKind] = frozenset({'normal'})
_PROPAGATING_LOOP_OUTCOMES: frozenset[CompletionKind] = frozenset({'return', 'error', 'halt'})


class UnreachableCodeChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unreachable-code'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'hint'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        _script_outcomes(
            context.facts.control_flow,
            context=context,
            report_unreachable=False,
            emit=lambda span: diagnostics.append(
                self.emit(
                    span=span,
                    message='Command is unreachable.',
                    tags=('unnecessary',),
                )
            ),
        )
        return diagnostics


def _script_outcomes(
    script: ControlFlowScript,
    *,
    context: DiagnosticContext,
    report_unreachable: bool,
    emit: DiagnosticEmitter,
) -> frozenset[CompletionKind]:
    outcomes: set[CompletionKind] = set()
    reachable = True

    for command in script.commands:
        if not reachable:
            if report_unreachable:
                emit(_diagnostic_span(command))
            continue

        command_outcomes = _command_outcomes(
            command,
            context=context,
            report_unreachable=True,
            emit=emit,
        )
        outcomes.update(outcome for outcome in command_outcomes if outcome != 'normal')
        reachable = 'normal' in command_outcomes

    if reachable:
        outcomes.add('normal')
    return frozenset(outcomes)


def _command_outcomes(
    command: ControlFlowCommand,
    *,
    context: DiagnosticContext,
    report_unreachable: bool,
    emit: DiagnosticEmitter,
) -> frozenset[CompletionKind]:
    if isinstance(command, ProcControlFlowCommand):
        _body_outcomes(
            command.body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
        return _NORMAL
    if isinstance(command, NamespaceEvalControlFlowCommand):
        return _body_outcomes(
            command.body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
    if isinstance(command, IfControlFlowCommand):
        if_outcomes: set[CompletionKind] = set()
        later_clauses_reachable = True
        for clause in command.clauses:
            if not later_clauses_reachable:
                _emit_unreachable_script(clause.body, emit)
                continue

            true_possible, false_possible = _condition_truth_possibilities(clause.condition_text)
            if not true_possible:
                _emit_unreachable_script(clause.body, emit)
                continue

            if_outcomes.update(
                _body_outcomes(
                    clause.body,
                    context=context,
                    report_unreachable=report_unreachable,
                    emit=emit,
                )
            )
            if not false_possible:
                later_clauses_reachable = False
        if command.else_body is None:
            if later_clauses_reachable:
                if_outcomes.add('normal')
        else:
            if later_clauses_reachable:
                if_outcomes.update(
                    _body_outcomes(
                        command.else_body,
                        context=context,
                        report_unreachable=report_unreachable,
                        emit=emit,
                    )
                )
            else:
                _emit_unreachable_script(command.else_body, emit)
        return frozenset(if_outcomes or _NORMAL)
    if isinstance(command, CatchControlFlowCommand):
        body_outcomes = _body_outcomes(
            command.body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
        if 'halt' in body_outcomes:
            return frozenset({'normal', 'halt'})
        return _NORMAL
    if isinstance(command, ForControlFlowCommand):
        start_outcomes = _body_outcomes(
            command.start_body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
        outcomes = {outcome for outcome in start_outcomes if outcome in _PROPAGATING_LOOP_OUTCOMES}
        if 'normal' not in start_outcomes:
            return frozenset(outcomes or _NORMAL)
        outcomes.add('normal')
        for loop_script in (command.body, command.next_body):
            outcomes.update(
                outcome
                for outcome in _body_outcomes(
                    loop_script,
                    context=context,
                    report_unreachable=report_unreachable,
                    emit=emit,
                )
                if outcome in _PROPAGATING_LOOP_OUTCOMES
            )
        return frozenset(outcomes)
    if isinstance(command, WhileControlFlowCommand):
        true_possible, _ = _condition_truth_possibilities(command.condition_text)
        if not true_possible:
            _emit_unreachable_script(command.body, emit)
            return _NORMAL

        outcomes = {'normal'}
        outcomes.update(
            outcome
            for outcome in _body_outcomes(
                command.body,
                context=context,
                report_unreachable=report_unreachable,
                emit=emit,
            )
            if outcome in _PROPAGATING_LOOP_OUTCOMES
        )
        return frozenset(outcomes)
    if isinstance(command, SwitchControlFlowCommand):
        if not command.branch_bodies:
            return _NORMAL

        outcomes: set[CompletionKind] = set()
        for branch_body in command.branch_bodies:
            outcomes.update(
                _switch_branch_outcomes(
                    branch_body,
                    context=context,
                    report_unreachable=report_unreachable,
                    emit=emit,
                )
            )
        if not command.has_default:
            outcomes.add('normal')
        return frozenset(outcomes)
    if isinstance(command, TryControlFlowCommand):
        body_outcomes = _body_outcomes(
            command.body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
        handler_outcomes = tuple(
            _body_outcomes(
                handler,
                context=context,
                report_unreachable=report_unreachable,
                emit=emit,
            )
            for handler in command.handlers
        )
        finally_outcomes = _body_outcomes(
            command.finally_body,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
        if command.finally_body is not None:
            if 'normal' not in finally_outcomes:
                return finally_outcomes
            outcomes = set(finally_outcomes)
            if 'halt' in body_outcomes or any('halt' in outcomes for outcomes in handler_outcomes):
                outcomes.add('halt')
            return frozenset(outcomes)
        if 'halt' in body_outcomes or any('halt' in outcomes for outcomes in handler_outcomes):
            return frozenset({'normal', 'halt'})
        return _NORMAL

    builtin = _resolved_builtin(command, context)
    if builtin is None:
        return _NORMAL

    match builtin.name:
        case 'return' | 'tailcall':
            return frozenset({'return'})
        case 'break':
            return frozenset({'break'})
        case 'continue':
            return frozenset({'continue'})
        case 'error' | 'throw':
            return frozenset({'error'})
        case 'exit':
            return frozenset({'halt'})
        case _:
            return _NORMAL


def _body_outcomes(
    script: ControlFlowScript | None,
    *,
    context: DiagnosticContext,
    report_unreachable: bool,
    emit: DiagnosticEmitter,
) -> frozenset[CompletionKind]:
    if script is None:
        return _NORMAL
    return _script_outcomes(
        script,
        context=context,
        report_unreachable=report_unreachable,
        emit=emit,
    )


def _switch_branch_outcomes(
    script: ControlFlowScript,
    *,
    context: DiagnosticContext,
    report_unreachable: bool,
    emit: DiagnosticEmitter,
) -> frozenset[CompletionKind]:
    outcomes = set(
        _script_outcomes(
            script,
            context=context,
            report_unreachable=report_unreachable,
            emit=emit,
        )
    )
    if 'break' in outcomes:
        outcomes.discard('break')
        outcomes.add('normal')
    return frozenset(outcomes)


def _emit_unreachable_script(
    script: ControlFlowScript | None,
    emit: DiagnosticEmitter,
) -> None:
    if script is None:
        return
    for command in script.commands:
        emit(_diagnostic_span(command))


def _condition_truth_possibilities(condition_text: str | None) -> tuple[bool, bool]:
    if condition_text is None:
        return True, True
    result = eval_expr_text(
        VariableFlowState.empty(),
        condition_text,
        lambda _script_text, _state: (),
    )
    return result.true_possible, result.false_possible


def _resolved_builtin(
    command: ControlFlowCommand,
    context: DiagnosticContext,
) -> BuiltinCommand | None:
    key = _command_key(context.facts.uri, command)
    if key is None:
        return None
    target = context.command_targets.get(key)
    if not isinstance(target, BuiltinCommand):
        return None
    return target


def _command_key(uri: str, command: ControlFlowCommand) -> CommandCallKey | None:
    if command.name_span is None:
        return None
    return (
        uri,
        command.span.start.offset,
        command.span.end.offset,
        command.name_span.start.offset,
        command.name_span.end.offset,
    )


def _diagnostic_span(command: ControlFlowCommand) -> Span:
    return command.span
