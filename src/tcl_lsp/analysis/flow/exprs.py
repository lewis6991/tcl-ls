from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from tcl_lsp.analysis.facts.parsing import is_simple_name
from tcl_lsp.analysis.types import LiteralType, NamedType, UnionType, literal_values
from tcl_lsp.analysis.value_constraints import (
    literal_accepts,
    numeric_or_string_equal,
    truth_value,
    union_nodes,
    validation_guard,
)
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
    return expr_branch_states(state, expr)


def expr_branch_states(
    state: VariableFlowState, expr: Expr
) -> tuple[VariableFlowState, VariableFlowState]:
    analyzer = _ExprAnalyzer()
    true_state, false_state = analyzer.branch_flow_states(state, expr)
    result = analyzer.eval_expr(state, expr)
    return (
        replace(true_state, reachable=true_state.reachable and result.true_possible),
        replace(false_state, reachable=false_state.reachable and result.false_possible),
    )


def eval_expr_text(
    state: VariableFlowState,
    expr_text: str,
    script_val_resolver: ScriptValResolver,
) -> ExprEval:
    expr = parse_expr(expr_text)
    if expr is None:
        return ExprEval.unknown()
    return eval_expr(state, expr, script_val_resolver)


def eval_expr(
    state: VariableFlowState,
    expr: Expr,
    script_val_resolver: ScriptValResolver,
) -> ExprEval:
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
            case ExprCommandSubstitution(script_text):
                # Only the strict, side-effect-free validation form is a guard.
                guard = validation_guard(script_text)
                if guard is None:
                    return state, state
                name, info = guard
                true_state = state.with_type(name, info)
                values = state.exact_values(name)
                if values:
                    kind = 'number' if info.resolved == NamedType('number') else 'integer'
                    accepted = tuple(
                        value for value in values if literal_accepts(value, kind) is not False
                    )
                    true_state = true_state.with_exact_values(name, accepted)
                    true_state = replace(true_state, reachable=state.reachable and bool(accepted))
                return true_state, state
            case ExprUnary('!', operand):
                false_state, true_state = self.branch_flow_states(state, operand)
                return true_state, false_state
            case ExprBinary('&&', left, right):
                left_true_state, left_false_state = self.branch_flow_states(state, left)
                right_true_state, right_false_state = self.branch_flow_states(
                    left_true_state, right
                )
                return right_true_state, type(state).join(left_false_state, right_false_state)
            case ExprBinary('||', left, right):
                left_true_state, left_false_state = self.branch_flow_states(state, left)
                right_true_state, right_false_state = self.branch_flow_states(
                    left_false_state, right
                )
                return type(state).join(left_true_state, right_true_state), right_false_state
            case _:
                return state, state

    def eval_expr(
        self,
        state: VariableFlowState,
        expr: Expr,
    ) -> ExprEval:
        match expr:
            case ExprAtom():
                return ExprEval.from_values(expr_atom_values(expr, state))
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
                values_known = True
                true_possible = False
                false_possible = False
                if cond.true_possible:
                    true_branch = self.eval_expr(true_state, true_expr)
                    values_known = values_known and bool(true_branch.values)
                    _append_unique_values(values, true_branch.values)
                    true_possible = true_possible or true_branch.true_possible
                    false_possible = false_possible or true_branch.false_possible
                if cond.false_possible:
                    false_branch = self.eval_expr(false_state, false_expr)
                    values_known = values_known and bool(false_branch.values)
                    _append_unique_values(values, false_branch.values)
                    true_possible = true_possible or false_branch.true_possible
                    false_possible = false_possible or false_branch.false_possible
                return ExprEval(
                    tuple(values) if values_known else (), true_possible, false_possible
                )
            case _:
                return ExprEval.unknown()

    def _comparison_branch_flow_states(
        self,
        state: VariableFlowState,
        comparison: _CondComparison,
    ) -> tuple[VariableFlowState, VariableFlowState]:
        if comparison.operator in {'==', '!='}:
            # Numeric equality says nothing about the original spelling.
            values = state.exact_values(comparison.var_name)
            results = tuple(
                numeric_or_string_equal(value, comparison.literal_value) for value in values
            )
            if not results or None in results:
                return state, state
            equal = state.with_exact_values(
                comparison.var_name,
                tuple(value for value, result in zip(values, results, strict=True) if result),
            )
            different = state.with_exact_values(
                comparison.var_name,
                tuple(value for value, result in zip(values, results, strict=True) if not result),
            )
            equal = equal.guarded(comparison.var_name)
            different = different.guarded(comparison.var_name)
            return (equal, different) if comparison.operator == '==' else (different, equal)
        equal = state.with_exact_values(comparison.var_name, (comparison.literal_value,))
        different = _state_without_exact_value(state, comparison.var_name, comparison.literal_value)
        equal = equal.guarded(comparison.var_name)
        different = different.guarded(comparison.var_name)
        match comparison.operator:
            case 'eq':
                return equal, different
            case _:
                return different, equal

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
                var_name = expr_atom_variable(expr)
                if var_name is not None:
                    return 'var', var_name
                if expr_atom_values(expr, None):
                    return 'literal', text
                return None
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
                equal = left_value == right_value
                if expr.operator in {'==', '!='}:
                    comparison = numeric_or_string_equal(left_value, right_value)
                    if comparison is None:
                        return ExprEval.unknown()
                    equal = comparison
                _append_unique_value(
                    values,
                    '1' if (equal if expr.operator in {'eq', '=='} else not equal) else '0',
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

    def _script_values(
        self,
        script_text: str,
        state: VariableFlowState,
    ) -> tuple[str, ...]:
        guard = validation_guard(script_text)
        if guard:
            name, info = guard
            values = state.exact_values(name)
            kind = 'number' if info.resolved == NamedType('number') else 'integer'
            checks = tuple(literal_accepts(value, kind) for value in values)
            if checks and None not in checks:
                # `string is integer` has a bounded range; `entier` does not.
                if 'entier' in script_text or kind == 'number' or not any(checks):
                    return tuple(dict.fromkeys('1' if check else '0' for check in checks))
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
    return truth_value(text)


def expr_atom_variable(atom: ExprAtom) -> str | None:
    if atom.kind not in {'variable', 'quoted'}:
        return None
    text = atom.text
    if text.startswith('${') and text.endswith('}'):
        name = text[2:-1]
    elif text.startswith('$'):
        name = text[1:]
    else:
        return None
    return name if is_simple_name(name) else None


def expr_atom_values(atom: ExprAtom, state: VariableFlowState | None) -> tuple[str, ...]:
    name = expr_atom_variable(atom)
    if name is not None:
        return state.exact_values(name) if state else ()
    if atom.kind == 'unknown' or (
        atom.kind in {'variable', 'quoted'} and any(char in atom.text for char in '$[')
    ):
        return ()
    return (atom.text,)


def _state_without_exact_value(
    state: VariableFlowState,
    name: str,
    value: str,
) -> VariableFlowState:
    existing_values = state.exact_values(name)
    if existing_values:
        state = state.with_exact_values(
            name, tuple(existing for existing in existing_values if existing != value)
        )
    info = state.type_info(name)
    if info and isinstance(info.resolved, UnionType) and not literal_values(info.resolved):
        remaining = tuple(
            node
            for node in info.resolved.members
            if not isinstance(node, LiteralType) or node.value != value
        )
        if remaining:
            state = state.with_type(name, replace(info, resolved=union_nodes(remaining)))
    return state


def _append_unique_values(values: list[str], new_values: tuple[str, ...]) -> None:
    for value in new_values:
        _append_unique_value(values, value)


def _append_unique_value(values: list[str], new_value: str) -> None:
    if new_value in values:
        return
    values.append(new_value)
