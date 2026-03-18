from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.facts.parsing import is_simple_name, split_tcl_list
from tcl_lsp.common import Position
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    VariableSubstitution,
    Word,
)

_ZERO_POSITION = Position(offset=0, line=0, character=0)


@dataclass(frozen=True, slots=True)
class VariableFlowState:
    exact_values_by_name: dict[str, tuple[str, ...]]

    @classmethod
    def empty(cls) -> VariableFlowState:
        return cls({})

    def exact_values(self, name: str) -> tuple[str, ...]:
        return self.exact_values_by_name.get(name, ())

    def with_exact_values(
        self,
        name: str,
        values: tuple[str, ...],
    ) -> VariableFlowState:
        next_values_by_name = dict(self.exact_values_by_name)
        if values:
            next_values_by_name[name] = values
        else:
            next_values_by_name.pop(name, None)
        return VariableFlowState(next_values_by_name)

    def without_names(self, names: tuple[str, ...]) -> VariableFlowState:
        if not names:
            return self

        next_values_by_name = dict(self.exact_values_by_name)
        changed = False
        for name in names:
            if name not in next_values_by_name:
                continue
            changed = True
            next_values_by_name.pop(name)
        if not changed:
            return self
        return VariableFlowState(next_values_by_name)

    def merged(self, domains: dict[str, tuple[str, ...]]) -> VariableFlowState:
        if not domains:
            return self
        next_values_by_name = dict(self.exact_values_by_name)
        next_values_by_name.update(domains)
        return VariableFlowState(next_values_by_name)


@dataclass(frozen=True, slots=True)
class _ConditionComparison:
    variable_name: str
    operator: str
    literal_value: str


def normalize_variable_name(name: str) -> str:
    while name.endswith(':') and not name.endswith('::'):
        name = name[:-1]

    open_paren = name.find('(')
    if open_paren <= 0 or not name.endswith(')'):
        return name

    base_name = name[:open_paren]
    if not is_simple_name(base_name):
        return name
    return base_name


def exact_word_values(word: Word, state: VariableFlowState) -> tuple[str, ...]:
    static_text = word_static_text(word)
    if static_text is not None:
        return (static_text,)

    if isinstance(word, BracedWord) or len(word.parts) != 1:
        return ()

    part = word.parts[0]
    if not isinstance(part, VariableSubstitution):
        if not isinstance(part, CommandSubstitution):
            return ()
        return _command_substitution_values(part, state)
    return state.exact_values(part.name)


def dynamic_variable_target_names(
    word: Word,
    state: VariableFlowState,
) -> tuple[str, ...]:
    names: list[str] = []
    for value in exact_word_values(word, state):
        normalized_name = normalize_variable_name(value)
        if not is_simple_name(normalized_name) or normalized_name in names:
            continue
        names.append(normalized_name)
    return tuple(names)


def script_body_flow_state(
    state: VariableFlowState,
    *,
    metadata_command_name: str,
    argument_words: tuple[Word, ...],
    selected_word: Word,
) -> VariableFlowState:
    if metadata_command_name not in {'foreach', 'lmap'} or not argument_words:
        return state
    if selected_word is not argument_words[-1]:
        return state

    return state.merged(_foreach_like_variable_domains(argument_words[:-1], state))


def condition_branch_flow_states(
    state: VariableFlowState,
    condition_text: str,
) -> tuple[VariableFlowState, VariableFlowState]:
    comparison = _condition_comparison(condition_text)
    if comparison is None:
        return state, state

    if comparison.operator in {'eq', '=='}:
        return (
            state.with_exact_values(comparison.variable_name, (comparison.literal_value,)),
            _state_without_exact_value(state, comparison.variable_name, comparison.literal_value),
        )

    return (
        _state_without_exact_value(state, comparison.variable_name, comparison.literal_value),
        state.with_exact_values(comparison.variable_name, (comparison.literal_value,)),
    )


def state_with_set_command(
    state: VariableFlowState,
    command: Command,
) -> VariableFlowState:
    if len(command.words) < 2:
        return state

    target_name = _simple_variable_name(command.words[1])
    if target_name is not None:
        if len(command.words) < 3:
            return state
        return state.with_exact_values(target_name, exact_word_values(command.words[2], state))

    dynamic_names = dynamic_variable_target_names(command.words[1], state)
    if not dynamic_names or len(command.words) < 3:
        return state

    next_state = state
    values = exact_word_values(command.words[2], state)
    for name in dynamic_names:
        next_state = next_state.with_exact_values(name, values)
    return next_state


def state_with_unset_command(
    state: VariableFlowState,
    command: Command,
) -> VariableFlowState:
    names: list[str] = []
    for word in unset_target_words(command):
        target_name = _simple_variable_name(word)
        if target_name is not None:
            if target_name not in names:
                names.append(target_name)
            continue
        for dynamic_name in dynamic_variable_target_names(word, state):
            if dynamic_name not in names:
                names.append(dynamic_name)
    return state.without_names(tuple(names))


def unset_target_words(command: Command) -> tuple[Word, ...]:
    targets: list[Word] = []
    options_done = False
    for word in command.words[1:]:
        static_text = word_static_text(word)
        if not options_done and static_text == '--':
            options_done = True
            continue
        if not options_done and static_text == '-nocomplain':
            continue
        options_done = True
        targets.append(word)
    return tuple(targets)


def _simple_variable_name(word: Word) -> str | None:
    variable_name = normalize_variable_name(word_static_text(word) or '')
    if not variable_name or not is_simple_name(variable_name):
        return None
    return variable_name


def _exact_list_item_texts(
    word: Word,
    state: VariableFlowState,
) -> tuple[str, ...]:
    items: list[str] = []
    for value in exact_word_values(word, state):
        for item in split_tcl_list(value, _ZERO_POSITION):
            if item.text in items:
                continue
            items.append(item.text)
    return tuple(items)


def _foreach_like_variable_domains(
    argument_words: tuple[Word, ...],
    state: VariableFlowState,
) -> dict[str, tuple[str, ...]]:
    if len(argument_words) < 2:
        return {}

    domains: dict[str, list[str]] = {}
    pair_words = argument_words[: len(argument_words) - (len(argument_words) % 2)]
    for index in range(0, len(pair_words), 2):
        variable_items = _exact_list_item_texts(pair_words[index], state)
        value_items = _exact_list_item_texts(pair_words[index + 1], state)
        if not variable_items or not value_items:
            continue

        variable_count = len(variable_items)
        for variable_index, variable_name in enumerate(variable_items):
            if not is_simple_name(variable_name):
                continue
            values = value_items[variable_index::variable_count]
            if not values:
                continue

            existing_values = domains.setdefault(variable_name, [])
            for value in values:
                if value in existing_values:
                    continue
                existing_values.append(value)

    return {name: tuple(values) for name, values in domains.items()}


def _condition_comparison(text: str) -> _ConditionComparison | None:
    items = split_tcl_list(text, _ZERO_POSITION)
    if len(items) != 3:
        return None

    left = _condition_operand(items[0].text)
    operator = items[1].text
    right = _condition_operand(items[2].text)
    if operator not in {'eq', 'ne', '==', '!='}:
        return None
    if left is None or right is None or left[0] == right[0]:
        return None

    variable_name = left[1] if left[0] == 'variable' else right[1]
    literal_value = right[1] if left[0] == 'variable' else left[1]
    return _ConditionComparison(
        variable_name=variable_name,
        operator=operator,
        literal_value=literal_value,
    )


def _condition_operand(text: str) -> tuple[str, str] | None:
    if text.startswith('${') and text.endswith('}'):
        variable_name = text[2:-1].strip()
        if is_simple_name(variable_name):
            return 'variable', variable_name
        return None

    if text.startswith('$'):
        variable_name = text[1:]
        if is_simple_name(variable_name):
            return 'variable', variable_name
        return None

    return 'literal', text


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


def _command_substitution_values(
    substitution: CommandSubstitution,
    state: VariableFlowState,
) -> tuple[str, ...]:
    script = substitution.script
    if len(script.commands) != 1:
        return ()

    command = script.commands[0]
    if len(command.words) != 2 or word_static_text(command.words[0]) != 'expr':
        return ()

    expression_text = word_static_text(command.words[1])
    if expression_text is None:
        return ()

    ternary_parts = _split_top_level_ternary(expression_text)
    if ternary_parts is None:
        return ()

    condition_text, true_text, false_text = ternary_parts
    true_possible, false_possible = _condition_branch_possibilities(state, condition_text)
    values: list[str] = []
    if true_possible:
        for value in _expr_result_values(true_text, state):
            if value not in values:
                values.append(value)
    if false_possible:
        for value in _expr_result_values(false_text, state):
            if value not in values:
                values.append(value)
    return tuple(values)


def _expr_result_values(
    text: str,
    state: VariableFlowState,
) -> tuple[str, ...]:
    items = split_tcl_list(text.strip(), _ZERO_POSITION)
    if len(items) != 1:
        return ()

    item_text = items[0].text
    variable_name = _expr_variable_name(item_text)
    if variable_name is None:
        return (item_text,)
    return state.exact_values(variable_name)


def _expr_variable_name(text: str) -> str | None:
    if text.startswith('${') and text.endswith('}'):
        variable_name = text[2:-1].strip()
        if is_simple_name(variable_name):
            return variable_name
        return None

    if not text.startswith('$'):
        return None

    variable_name = text[1:]
    if not is_simple_name(variable_name):
        return None
    return variable_name


def _condition_branch_possibilities(
    state: VariableFlowState,
    condition_text: str,
) -> tuple[bool, bool]:
    comparison = _condition_comparison(condition_text)
    if comparison is None:
        return True, True

    exact_values = state.exact_values(comparison.variable_name)
    if not exact_values:
        return True, True

    true_possible = any(
        _condition_value_matches(
            value,
            operator=comparison.operator,
            literal_value=comparison.literal_value,
        )
        for value in exact_values
    )
    false_possible = any(
        not _condition_value_matches(
            value,
            operator=comparison.operator,
            literal_value=comparison.literal_value,
        )
        for value in exact_values
    )
    return true_possible, false_possible


def _condition_value_matches(
    value: str,
    *,
    operator: str,
    literal_value: str,
) -> bool:
    if operator in {'eq', '=='}:
        return value == literal_value
    return value != literal_value


def _split_top_level_ternary(text: str) -> tuple[str, str, str] | None:
    question_index: int | None = None
    ternary_depth = 0
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0
    in_quote = False
    index = 0

    while index < len(text):
        current_char = text[index]
        if current_char == '\\':
            index += 2
            continue

        if in_quote:
            if current_char == '"':
                in_quote = False
            index += 1
            continue

        if current_char == '"':
            in_quote = True
            index += 1
            continue
        if current_char == '(':
            paren_depth += 1
            index += 1
            continue
        if current_char == ')' and paren_depth > 0:
            paren_depth -= 1
            index += 1
            continue
        if current_char == '{':
            brace_depth += 1
            index += 1
            continue
        if current_char == '}' and brace_depth > 0:
            brace_depth -= 1
            index += 1
            continue
        if current_char == '[':
            bracket_depth += 1
            index += 1
            continue
        if current_char == ']' and bracket_depth > 0:
            bracket_depth -= 1
            index += 1
            continue

        if paren_depth or brace_depth or bracket_depth:
            index += 1
            continue

        if current_char == '?':
            if question_index is None:
                question_index = index
            else:
                ternary_depth += 1
            index += 1
            continue
        if current_char == ':' and question_index is not None:
            if ternary_depth == 0:
                return (
                    text[:question_index].strip(),
                    text[question_index + 1 : index].strip(),
                    text[index + 1 :].strip(),
                )
            ternary_depth -= 1
        index += 1

    return None
