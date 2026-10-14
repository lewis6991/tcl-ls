"""Check operator requirements without evaluating Tcl code or substitutions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tcl_lsp.analysis.flow.exprs import (
    eval_expr,
    expr_atom_values,
    expr_atom_variable,
    expr_branch_states,
)
from tcl_lsp.analysis.flow.variables import VariableFlowState, exact_list_values
from tcl_lsp.analysis.types import ListType, NamedType, TypeInfo, TypeNode, type_text
from tcl_lsp.analysis.value_constraints import (
    Interpretation,
    accepts,
    literal_matches,
    rejected_alternatives,
    union_nodes,
    validation_guard,
    value_constraint,
)
from tcl_lsp.common import Diagnostic, Span
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.expr import (
    Expr,
    ExprAtom,
    ExprBinary,
    ExprCommandSubstitution,
    ExprFunctionCall,
    ExprTernary,
    ExprUnary,
    parse_expr_result,
)
from tcl_lsp.parser.model import ParseResult

_INTEGER_OPERATORS = frozenset({'%', '&', '|', '^', '<<', '>>'})
_NUMBER_OPERATORS = frozenset({'+', '-', '*', '/', '**'})
_VALUE_PARSER = Parser()
type ScriptEffects = Callable[[ParseResult, VariableFlowState], VariableFlowState]


@dataclass(frozen=True, slots=True)
class ExpressionAnalysis:
    diagnostics: tuple[Diagnostic, ...]
    state: VariableFlowState


def analyze_expression(
    text: str,
    span: Span,
    state: VariableFlowState,
    *,
    condition: bool = False,
    script_effects: ScriptEffects | None = None,
) -> ExpressionAnalysis:
    if not state.reachable:
        return ExpressionAnalysis((), state)
    try:
        parsed = parse_expr_result(text)
        expr = parsed.expression
        if expr is None:
            if parsed.invalid:
                return ExpressionAnalysis(
                    (
                        Diagnostic(
                            span=span,
                            severity='error',
                            message='Invalid expression syntax.',
                            source='analysis',
                            code='invalid-expr',
                        ),
                    ),
                    state,
                )
            # Unmodelled syntax must not become an error.
            return ExpressionAnalysis((), state.invalidated())
        checker = _OperandChecker(span, script_effects=script_effects)
        node, state = checker.evaluate(expr, state)
        if condition:
            checker.require(node, 'truth', 'condition')
        return ExpressionAnalysis(tuple(checker.diagnostics), state)
    except RecursionError:
        return ExpressionAnalysis((), state.invalidated())


def assignment_diagnostics(
    values: tuple[str, ...], info: TypeInfo, span: Span
) -> tuple[Diagnostic, ...]:
    results = tuple(literal_matches(value, info.resolved) for value in values)
    if False not in results:
        return ()
    definite = all(result is False for result in results)
    return (
        Diagnostic(
            span=span,
            severity='error' if definite else 'warning',
            message=(
                f'Assigned value {"does not" if definite else "may not"} satisfy '
                f'`{info.expression.text}`.'
            ),
            source='analysis',
            code='invalid-value',
        ),
    )


@dataclass(slots=True)
class _OperandChecker:
    span: Span
    diagnostics: list[Diagnostic] = field(default_factory=list)
    script_effects: ScriptEffects | None = None

    def require(self, node: TypeNode | None, kind: Interpretation, operator: str) -> bool:
        rejected, definite = rejected_alternatives(node, kind)
        if not rejected:
            return True
        expected = {
            'integer': 'an integer',
            'number': 'a number',
            'truth': 'a boolean or number',
            'list': 'a valid Tcl list',
        }[kind]
        values = type_text(union_nodes(rejected))
        self.diagnostics.append(
            Diagnostic(
                span=self.span,
                severity='error' if definite else 'warning',
                message=(
                    f'Operator `{operator}` requires {expected}; '
                    f'operand {"is" if definite else "can be"} `{values}`.'
                ),
                source='analysis',
                code='invalid-expr-operand',
            )
        )
        return False

    def evaluate(
        self, expr: Expr, state: VariableFlowState
    ) -> tuple[TypeNode | None, VariableFlowState]:
        if not state.reachable:
            return None, state
        match expr:
            case ExprAtom():
                name = expr_atom_variable(expr)
                info = state.type_info(name) if name else None
                return value_constraint(expr_atom_values(expr, state), info), state

            case ExprCommandSubstitution(script_text):
                return self.script_value(script_text, state)

            case ExprUnary(operator, operand):
                node, state = self.evaluate(operand, state)
                kind = 'truth' if operator == '!' else 'integer' if operator == '~' else 'number'
                valid = self.require(node, kind, operator)
                result = 'integer' if kind in {'truth', 'integer'} else 'number'
                return NamedType(result) if valid else None, state

            case ExprBinary('&&' | '||' as operator, left, right):
                left_node, state = self.evaluate(left, state)
                left_valid = self.require(left_node, 'truth', operator)
                truth = eval_expr(state, left, lambda _script, _state: ())
                needed = truth.true_possible if operator == '&&' else truth.false_possible
                if needed:
                    true_state, false_state = self.branches(state, left)
                    right_state = true_state if operator == '&&' else false_state
                    right_node, right_state = self.evaluate(right, right_state)
                    self.require(right_node, 'truth', operator)
                    state = VariableFlowState.join(state, right_state)
                return NamedType('integer') if left_valid else None, state

            case ExprBinary(operator, left, right):
                left_node, state = self.evaluate(left, state)
                right_node, state = self.evaluate(right, state)
                if operator in _INTEGER_OPERATORS or operator in _NUMBER_OPERATORS:
                    kind = 'integer' if operator in _INTEGER_OPERATORS else 'number'
                    left_valid = self.require(left_node, kind, operator)
                    right_valid = self.require(right_node, kind, operator)
                    if not left_valid or not right_valid:
                        return None, state
                    integer = (
                        accepts(left_node, 'integer') is True
                        and accepts(right_node, 'integer') is True
                    )
                    return NamedType('integer' if integer or kind == 'integer' else 'number'), state
                if operator in {'in', 'ni'}:
                    self.require(right_node, 'list', operator)
                return NamedType('integer'), state

            case ExprTernary(condition, true_expr, false_expr):
                node, state = self.evaluate(condition, state)
                self.require(node, 'truth', '?:')
                truth = eval_expr(state, condition, lambda _script, _state: ())
                true_state, false_state = self.branches(state, condition)
                nodes: list[TypeNode | None] = []
                exits: list[VariableFlowState] = []
                for possible, branch, branch_state in (
                    (truth.true_possible, true_expr, true_state),
                    (truth.false_possible, false_expr, false_state),
                ):
                    if possible:
                        branch_node, branch_state = self.evaluate(branch, branch_state)
                        nodes.append(branch_node)
                        exits.append(branch_state)
                result = (
                    None if None in nodes else union_nodes(tuple(n for n in nodes if n is not None))
                )
                return result, VariableFlowState.join(*exits)

            case ExprFunctionCall(_, arguments):
                for argument in arguments:
                    _, state = self.evaluate(argument, state)
                # Math functions are Tcl commands and can be replaced.
                return None, state.invalidated()

    @staticmethod
    def branches(
        state: VariableFlowState, expr: Expr
    ) -> tuple[VariableFlowState, VariableFlowState]:
        return expr_branch_states(state, expr)

    def script_value(
        self, text: str, state: VariableFlowState
    ) -> tuple[TypeNode | None, VariableFlowState]:
        parsed = _VALUE_PARSER.parse_document('expression', text)
        if parsed.diagnostics or len(parsed.script.commands) != 1:
            return None, state.invalidated()
        command = parsed.script.commands[0]
        words = command.words
        name = word_static_text(words[0]) if words else None
        after = self.script_effects(parsed, state) if self.script_effects else state.invalidated()
        if name in {'list', '::list'} and not any(word.expanded for word in words):
            state = after
            values = exact_list_values(words[1:], state)
            node = value_constraint(values, None) if values else ListType(NamedType('string'))
            return node, state
        if name in {'set', '::set'} and len(words) == 2:
            variable = word_static_text(words[1])
            if variable:
                return value_constraint(
                    state.exact_values(variable), state.type_info(variable)
                ), state
        if validation_guard(text):
            return NamedType('integer'), state
        return None, after
