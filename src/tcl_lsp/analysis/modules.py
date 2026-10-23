from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from tcl_lsp.analysis.flow import VariableFlowState
from tcl_lsp.analysis.flow.exprs import eval_expr, expr_atom_values
from tcl_lsp.common import Span
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.expr import (
    Expr,
    ExprAtom,
    ExprBinary,
    ExprCommandSubstitution,
    ExprUnary,
    parse_expr,
)
from tcl_lsp.project.config import ModuleRule


@dataclass(frozen=True, slots=True)
class ModuleSelection:
    span: Span
    modules: tuple[str, ...]


def active_modules(
    explicit: tuple[str, ...],
    rules: tuple[ModuleRule, ...],
    state: VariableFlowState,
) -> tuple[str, ...]:
    modules = list(explicit)
    for rule in rules:
        # Static expression analysis only; never execute command substitutions.
        result = eval_expr(state, rule.condition, _command_values)
        if result.true_possible and not result.false_possible and rule.name not in modules:
            modules.append(rule.name)
    return tuple(modules)


def module_condition_states(
    state: VariableFlowState, condition: str, rules: tuple[ModuleRule, ...]
) -> tuple[VariableFlowState, VariableFlowState]:
    """Narrow configured environment queries without executing their commands."""
    queries = _module_queries(rules)
    expr = parse_expr(condition) if queries else None
    if expr is None:
        return state, state
    return _query_branch_states(state, expr, queries)


def _query_branch_states(
    state: VariableFlowState, expr: Expr, queries: frozenset[tuple[str, ...]]
) -> tuple[VariableFlowState, VariableFlowState]:
    true_state = false_state = state
    comparison = _command_comparison(expr)
    if comparison is not None and comparison[0] in queries:
        command, operator, value = comparison
        values = state.module_command_values
        equal = replace(state, module_command_values=values | {command: (value,)})
        different_values = dict(values)
        remaining = tuple(item for item in values.get(command, ()) if item != value)
        if remaining:
            different_values[command] = remaining
        else:
            different_values.pop(command, None)
        different = replace(state, module_command_values=different_values)
        true_state, false_state = (equal, different) if operator == 'eq' else (different, equal)
    else:
        match expr:
            case ExprUnary('!', operand):
                false_state, true_state = _query_branch_states(state, operand, queries)
            case ExprBinary('&&', left, right):
                left_true, left_false = _query_branch_states(state, left, queries)
                true_state, right_false = _query_branch_states(left_true, right, queries)
                false_state = VariableFlowState.join(left_false, right_false)
            case ExprBinary('||', left, right):
                left_true, left_false = _query_branch_states(state, left, queries)
                right_true, false_state = _query_branch_states(left_false, right, queries)
                true_state = VariableFlowState.join(left_true, right_true)
            case _:
                pass
    result = eval_expr(state, expr, _command_values)
    return (
        replace(true_state, reachable=true_state.reachable and result.true_possible),
        replace(false_state, reachable=false_state.reachable and result.false_possible),
    )


@lru_cache(maxsize=256)
def _module_queries(rules: tuple[ModuleRule, ...]) -> frozenset[tuple[str, ...]]:
    def commands(expr: Expr) -> set[tuple[str, ...]]:
        comparison = _command_comparison(expr)
        if comparison is not None:
            return {comparison[0]}
        match expr:
            case ExprUnary(_, operand):
                return commands(operand)
            case ExprBinary(_, left, right):
                return commands(left) | commands(right)
            case _:
                return set()

    return frozenset(command for rule in rules for command in commands(rule.condition))


def _command_comparison(expr: Expr) -> tuple[tuple[str, ...], str, str] | None:
    match expr:
        case ExprBinary('eq' | 'ne', ExprCommandSubstitution(script), ExprAtom() as literal):
            pass
        case ExprBinary('eq' | 'ne', ExprAtom() as literal, ExprCommandSubstitution(script)):
            pass
        case _:
            return None
    command = _static_command(script)
    values = expr_atom_values(literal, None)
    return (command, expr.operator, values[0]) if command and values else None


@lru_cache(maxsize=256)
def _static_command(script: str) -> tuple[str, ...] | None:
    parsed = Parser().parse_document('module-condition', script)
    if parsed.diagnostics or len(parsed.script.commands) != 1:
        return None
    words: list[str] = []
    for word in parsed.script.commands[0].words:
        text = word_static_text(word)
        if text is None or word.expanded:
            return None
        words.append(text)
    return tuple(words) if words else None


def _command_values(script: str, state: VariableFlowState) -> tuple[str, ...]:
    command = _static_command(script)
    return state.module_command_values.get(command, ()) if command is not None else ()


def registry_at_offset(
    registry: MetadataRegistry, scopes: tuple[ModuleSelection, ...], offset: int
) -> MetadataRegistry:
    # A later directive or a nested Tcl body has the narrower containing span.
    scope = min(
        (scope for scope in scopes if scope.span.start.offset <= offset <= scope.span.end.offset),
        key=lambda scope: scope.span.end.offset - scope.span.start.offset,
        default=None,
    )
    return registry if scope is None else registry.with_modules(scope.modules)
