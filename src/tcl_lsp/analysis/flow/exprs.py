from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.parser.expr import (
    Expr,
    ExprAtom,
    ExprBinary,
    ExprCommandSubstitution,
    ExprTernary,
    ExprUnary,
    parse_expr,
)

if TYPE_CHECKING:
    from tcl_lsp.analysis.flow.variables import VariableFlowState

type ScriptValResolver = Callable[[str, VariableFlowState], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ExprEval:
    values: tuple[str, ...]
    true_possible: bool
    false_possible: bool

    @classmethod
    def unknown(cls) -> ExprEval:
        return cls((), True, True)

    @classmethod
    def from_values(cls, values: tuple[str, ...]) -> ExprEval:
        true_possible, false_possible = _truth_possibilities_from_values(values)
        return cls(values, true_possible, false_possible)

    @classmethod
    def from_truth_possibilities(
        cls,
        true_possible: bool,
        false_possible: bool,
    ) -> ExprEval:
        values: list[str] = []
        if true_possible:
            values.append('1')
        if false_possible:
            values.append('0')
        return cls(tuple(values), true_possible, false_possible)


@dataclass(frozen=True, slots=True)
class _CondComparison:
    var_name: str
    operator: str
    literal_value: str


def expr_branch_flow_states(
    state: VariableFlowState,
    expr_text: str,
) -> tuple[VariableFlowState, VariableFlowState]:
    expr = parse_expr(expr_text)
    if expr is None:
        return state, state
    return _ExprAnalyzer().branch_flow_states(state, expr)


def eval_expr_text(
    state: VariableFlowState,
    expr_text: str,
    script_val_resolver: ScriptValResolver,
) -> ExprEval:
    expr = parse_expr(expr_text)
    if expr is None:
        return ExprEval.unknown()
    return _ExprAnalyzer(script_val_resolver).eval_expr(state, expr)


class _ExprAnalyzer:
    __slots__ = ('_script_val_resolver',)

    def __init__(
        self,
        script_val_resolver: ScriptValResolver | None = None,
    ) -> None:
        self._script_val_resolver = script_val_resolver

    def branch_flow_states(
        self,
        state: VariableFlowState,
        expr: Expr,
    ) -> tuple[VariableFlowState, VariableFlowState]:
        comparison = self._expr_comparison(expr)
        if comparison is not None:
            return self._comparison_branch_flow_states(state, comparison)

        match expr:
            case ExprUnary('!', operand):
                false_state, true_state = self.branch_flow_states(state, operand)
                return true_state, false_state
            case ExprBinary('&&', left, right):
                left_true_state, left_false_state = self.branch_flow_states(state, left)
                right_true_state, right_false_state = self.branch_flow_states(
                    left_true_state, right
                )
                return right_true_state, _merge_possible_states(left_false_state, right_false_state)
            case ExprBinary('||', left, right):
                left_true_state, left_false_state = self.branch_flow_states(state, left)
                right_true_state, right_false_state = self.branch_flow_states(
                    left_false_state, right
                )
                return _merge_possible_states(left_true_state, right_true_state), right_false_state
            case _:
                return state, state

    def eval_expr(
        self,
        state: VariableFlowState,
        expr: Expr,
    ) -> ExprEval:
        match expr:
            case ExprAtom(text):
                return ExprEval.from_values(self._expr_atom_values(text, state))
            case ExprCommandSubstitution(script_text):
                return ExprEval.from_values(self._script_values(script_text, state))
            case ExprUnary('!', operand):
                operand_result = self.eval_expr(state, operand)
                return ExprEval.from_truth_possibilities(
                    operand_result.false_possible, operand_result.true_possible
                )
            case ExprUnary():
                return ExprEval.unknown()
            case ExprBinary('eq' | 'ne' | '==' | '!=', _, _):
                return self._eval_comparison(state, expr)
            case ExprBinary('&&', _, _):
                return self._eval_logical_and(state, expr)
            case ExprBinary('||', _, _):
                return self._eval_logical_or(state, expr)
            case ExprBinary():
                return ExprEval.unknown()
            case ExprTernary(cond_expr, true_expr, false_expr):
                cond = self.eval_expr(state, cond_expr)
                true_state, false_state = self.branch_flow_states(state, cond_expr)

                values: list[str] = []
                true_possible = False
                false_possible = False
                if cond.true_possible:
                    true_branch = self.eval_expr(true_state, true_expr)
                    _append_unique_values(values, true_branch.values)
                    true_possible = true_possible or true_branch.true_possible
                    false_possible = false_possible or true_branch.false_possible
                if cond.false_possible:
                    false_branch = self.eval_expr(false_state, false_expr)
                    _append_unique_values(values, false_branch.values)
                    true_possible = true_possible or false_branch.true_possible
                    false_possible = false_possible or false_branch.false_possible
                return ExprEval(tuple(values), true_possible, false_possible)
            case _:
                return ExprEval.unknown()

    def _comparison_branch_flow_states(
        self,
        state: VariableFlowState,
        comparison: _CondComparison,
    ) -> tuple[VariableFlowState, VariableFlowState]:
        match comparison.operator:
            case 'eq' | '==':
                return (
                    state.with_exact_values(comparison.var_name, (comparison.literal_value,)),
                    _state_without_exact_value(
                        state, comparison.var_name, comparison.literal_value
                    ),
                )
            case _:
                return (
                    _state_without_exact_value(
                        state, comparison.var_name, comparison.literal_value
                    ),
                    state.with_exact_values(comparison.var_name, (comparison.literal_value,)),
                )

    def _expr_comparison(self, expr: Expr) -> _CondComparison | None:
        match expr:
            case ExprBinary('eq' | 'ne' | '==' | '!=', left, right):
                pass
            case _:
                return None

        left = self._comparison_operand(left)
        right = self._comparison_operand(right)
        if left is None or right is None or left[0] == right[0]:
            return None

        var_name = left[1] if left[0] == 'var' else right[1]
        literal_value = right[1] if left[0] == 'var' else left[1]
        return _CondComparison(var_name, expr.operator, literal_value)

    def _comparison_operand(self, expr: Expr) -> tuple[str, str] | None:
        match expr:
            case ExprAtom(text):
                var_name = self._expr_atom_var_name(text)
                if var_name is not None:
                    return 'var', var_name
                return 'literal', text
            case _:
                return None

    def _eval_comparison(
        self,
        state: VariableFlowState,
        expr: ExprBinary,
    ) -> ExprEval:
        left = self.eval_expr(state, expr.left)
        right = self.eval_expr(state, expr.right)
        if not left.values or not right.values:
            return ExprEval.unknown()

        values: list[str] = []
        for left_value in left.values:
            for right_value in right.values:
                _append_unique_value(
                    values,
                    '1'
                    if (
                        left_value == right_value
                        if expr.operator in {'eq', '=='}
                        else left_value != right_value
                    )
                    else '0',
                )
        return ExprEval.from_values(tuple(values))

    def _eval_logical_and(
        self,
        state: VariableFlowState,
        expr: ExprBinary,
    ) -> ExprEval:
        left = self.eval_expr(state, expr.left)
        if not left.true_possible:
            return ExprEval.from_truth_possibilities(False, True)

        left_true_state, _ = self.branch_flow_states(state, expr.left)
        right = self.eval_expr(left_true_state, expr.right)
        return ExprEval.from_truth_possibilities(
            right.true_possible,
            left.false_possible or right.false_possible,
        )

    def _eval_logical_or(
        self,
        state: VariableFlowState,
        expr: ExprBinary,
    ) -> ExprEval:
        left = self.eval_expr(state, expr.left)
        if not left.false_possible:
            return ExprEval.from_truth_possibilities(True, False)

        _, left_false_state = self.branch_flow_states(state, expr.left)
        right = self.eval_expr(left_false_state, expr.right)
        return ExprEval.from_truth_possibilities(
            left.true_possible or right.true_possible,
            right.false_possible,
        )

    def _expr_atom_values(
        self,
        text: str,
        state: VariableFlowState,
    ) -> tuple[str, ...]:
        var_name = self._expr_atom_var_name(text)
        if var_name is None:
            return (text,)
        return state.exact_values(var_name)

    def _expr_atom_var_name(self, text: str) -> str | None:
        if text.startswith('${') and text.endswith('}'):
            var_name = text[2:-1].strip()
            if is_simple_name(var_name):
                return var_name
            return None

        if not text.startswith('$'):
            return None

        var_name = text[1:]
        if not is_simple_name(var_name):
            return None
        return var_name

    def _script_values(
        self,
        script_text: str,
        state: VariableFlowState,
    ) -> tuple[str, ...]:
        if self._script_val_resolver is None:
            return ()
        return self._script_val_resolver(script_text, state)


def _truth_possibilities_from_values(values: tuple[str, ...]) -> tuple[bool, bool]:
    if not values:
        return True, True

    true_possible = False
    false_possible = False
    for value in values:
        bool_value = _boolean_literal_value(value)
        if bool_value is None:
            return True, True
        if bool_value:
            true_possible = True
        else:
            false_possible = True
    return true_possible, false_possible


def _boolean_literal_value(text: str) -> bool | None:
    stripped_text = text.strip()
    lowered_text = stripped_text.lower()
    match lowered_text:
        case 'true' | 'yes' | 'on':
            return True
        case 'false' | 'no' | 'off':
            return False
        case _:
            pass

    try:
        return int(stripped_text, 10) != 0
    except ValueError:
        pass

    try:
        return float(stripped_text) != 0.0
    except ValueError:
        return None


def _state_without_exact_value(
    state: VariableFlowState,
    name: str,
    value: str,
) -> VariableFlowState:
    existing_values = state.exact_values(name)
    if not existing_values:
        return state

    remaining_values = tuple(existing for existing in existing_values if existing != value)
    return state.with_exact_values(name, remaining_values)


def _merge_possible_states(
    *states: VariableFlowState,
) -> VariableFlowState:
    first_state = states[0]
    candidate_names: list[str] = []
    for state in states:
        for name in state.exact_values_by_name:
            if name in candidate_names:
                continue
            candidate_names.append(name)

    merged_values_by_name: dict[str, tuple[str, ...]] = {}
    for name in candidate_names:
        if any(name not in state.exact_values_by_name for state in states):
            continue

        values: list[str] = []
        for state in states:
            _append_unique_values(values, state.exact_values_by_name[name])
        if values:
            merged_values_by_name[name] = tuple(values)

    return type(first_state)(merged_values_by_name)


def _append_unique_values(values: list[str], new_values: tuple[str, ...]) -> None:
    for value in new_values:
        _append_unique_value(values, value)


def _append_unique_value(values: list[str], new_value: str) -> None:
    if new_value in values:
        return
    values.append(new_value)
