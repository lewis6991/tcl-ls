from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.facts.parsing import is_simple_name, split_tcl_list
from tcl_lsp.analysis.flow.exprs import eval_expr_text, expr_branch_flow_states
from tcl_lsp.common import Diagnostic, Position
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    Script,
    VariableSubstitution,
    Word,
)

_ZERO_POSITION = Position(0, 0, 0)
_FLOW_PARSER = Parser()


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
class _SwitchCommandOptionState:
    value_index: int
    match_mode: str
    nocase: bool


@dataclass(frozen=True, slots=True)
class _SwitchCommandBranch:
    patterns: tuple[str | None, ...]
    body_text: str


@dataclass(frozen=True, slots=True)
class _SwitchCommandLayout:
    value_word: Word
    match_mode: str
    nocase: bool
    branches: tuple[_SwitchCommandBranch, ...]


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
        return _script_result_values(part.script, state)
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

    return state.merged(_foreach_like_var_domains(argument_words[:-1], state))


def condition_branch_flow_states(
    state: VariableFlowState,
    condition_text: str,
) -> tuple[VariableFlowState, VariableFlowState]:
    return expr_branch_flow_states(state, condition_text)


def switch_branch_flow_state(
    state: VariableFlowState,
    *,
    value_word: Word | None,
    match_mode: str,
    nocase: bool,
    patterns: tuple[str | None, ...],
) -> VariableFlowState:
    if value_word is None or nocase or not patterns:
        return state

    var_name = _switch_value_var_name(value_word)
    if var_name is None:
        return state

    branch_values = _switch_pattern_exact_values(patterns, match_mode)
    if not branch_values:
        return state

    current_values = state.exact_values(var_name)
    if current_values:
        narrowed_values = tuple(value for value in branch_values if value in current_values)
        if narrowed_values:
            return state.with_exact_values(var_name, narrowed_values)

    return state.with_exact_values(var_name, branch_values)


def state_with_set_command(
    state: VariableFlowState,
    command: Command,
) -> VariableFlowState:
    if len(command.words) < 2:
        return state

    target_name = _simple_var_name(command.words[1])
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
        target_name = _simple_var_name(word)
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


def _simple_var_name(word: Word) -> str | None:
    var_name = normalize_variable_name(word_static_text(word) or '')
    if not var_name or not is_simple_name(var_name):
        return None
    return var_name


def _switch_value_var_name(word: Word) -> str | None:
    if isinstance(word, BracedWord) or len(word.parts) != 1:
        return None

    part = word.parts[0]
    if not isinstance(part, VariableSubstitution):
        return None
    if not is_simple_name(part.name):
        return None
    return part.name


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


def _foreach_like_var_domains(
    argument_words: tuple[Word, ...],
    state: VariableFlowState,
) -> dict[str, tuple[str, ...]]:
    if len(argument_words) < 2:
        return {}

    domains: dict[str, list[str]] = {}
    pair_words = argument_words[: len(argument_words) - (len(argument_words) % 2)]
    for index in range(0, len(pair_words), 2):
        var_items = _exact_list_item_texts(pair_words[index], state)
        value_items = _exact_list_item_texts(pair_words[index + 1], state)
        if not var_items or not value_items:
            continue

        var_count = len(var_items)
        for var_index, var_name in enumerate(var_items):
            if not is_simple_name(var_name):
                continue
            values = value_items[var_index::var_count]
            if not values:
                continue

            existing_values = domains.setdefault(var_name, [])
            for value in values:
                if value in existing_values:
                    continue
                existing_values.append(value)

    return {name: tuple(values) for name, values in domains.items()}


def _switch_pattern_exact_values(
    patterns: tuple[str | None, ...],
    match_mode: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for pattern in patterns:
        exact_value = _switch_pattern_exact_value(pattern, match_mode)
        if exact_value is None:
            return ()
        if exact_value in values:
            continue
        values.append(exact_value)
    return tuple(values)


def _switch_pattern_exact_value(pattern: str | None, match_mode: str) -> str | None:
    if pattern is None or pattern == 'default':
        return None

    match match_mode:
        case 'exact':
            return pattern
        case 'glob':
            if any(char in pattern for char in '*?[]\\'):
                return None
            return pattern
        case 'regexp':
            if any(char in pattern for char in '.^$*+?()[]{}|\\'):
                return None
            return pattern
        case _:
            return None


def _switch_command_values(
    command: Command,
    state: VariableFlowState,
) -> tuple[str, ...]:
    layout = _switch_command_layout(command)
    if layout is None or layout.nocase:
        return ()

    var_name = _switch_value_var_name(layout.value_word)
    if var_name is None:
        return ()

    remaining_values = state.exact_values(var_name)
    if not remaining_values:
        return ()

    resolved_values: list[str] = []
    for branch in layout.branches:
        matched_values = _switch_branch_matched_values(
            remaining_values,
            branch.patterns,
            layout.match_mode,
        )
        if not matched_values:
            continue

        branch_state = state.with_exact_values(var_name, matched_values)
        branch_values = _embedded_script_result_values(branch.body_text, branch_state)
        if not branch_values:
            return ()

        for value in branch_values:
            if value in resolved_values:
                continue
            resolved_values.append(value)

        remaining_values = tuple(value for value in remaining_values if value not in matched_values)
        if not remaining_values:
            break

    if remaining_values:
        return ()
    return tuple(resolved_values)


def _switch_command_layout(command: Command) -> _SwitchCommandLayout | None:
    if len(command.words) < 3:
        return None

    option_state = _scan_switch_command_options(command.words)
    if option_state is None or option_state.value_index + 1 >= len(command.words):
        return None

    branch_words = command.words[option_state.value_index + 1 :]
    if len(branch_words) == 1:
        branches = _switch_command_branches_from_list_word(branch_words[0])
    else:
        branches = _switch_command_branches_from_words(branch_words)
    if not branches:
        return None

    return _SwitchCommandLayout(
        command.words[option_state.value_index],
        option_state.match_mode,
        option_state.nocase,
        branches,
    )


def _scan_switch_command_options(words: tuple[Word, ...]) -> _SwitchCommandOptionState | None:
    index = 1
    match_mode = 'exact'
    nocase = False

    while index < len(words):
        option = word_static_text(words[index])
        if option is None:
            break
        if option == '--':
            index += 1
            break
        if option == '-exact':
            match_mode = 'exact'
            index += 1
            continue
        if option == '-glob':
            match_mode = 'glob'
            index += 1
            continue
        if option == '-regexp':
            match_mode = 'regexp'
            index += 1
            continue
        if option == '-nocase':
            nocase = True
            index += 1
            continue
        if option in {'-matchvar', '-indexvar'}:
            if index + 1 >= len(words):
                return None
            index += 2
            continue
        if option.startswith('-'):
            return None
        break

    if index >= len(words):
        return None
    return _SwitchCommandOptionState(index, match_mode, nocase)


def _switch_command_branches_from_list_word(word: Word) -> tuple[_SwitchCommandBranch, ...]:
    branch_list_text = word_static_text(word)
    if branch_list_text is None:
        return ()

    items = split_tcl_list(branch_list_text, _ZERO_POSITION)
    if len(items) % 2 != 0:
        return ()

    branches: list[_SwitchCommandBranch] = []
    pending_patterns: list[str | None] = []
    for index in range(0, len(items), 2):
        pending_patterns.append(items[index].text)
        body_text = items[index + 1].text
        if body_text == '-':
            continue
        branches.append(_SwitchCommandBranch(tuple(pending_patterns), body_text))
        pending_patterns = []

    if pending_patterns:
        return ()
    return tuple(branches)


def _switch_command_branches_from_words(
    branch_words: tuple[Word, ...],
) -> tuple[_SwitchCommandBranch, ...]:
    if len(branch_words) % 2 != 0:
        return ()

    branches: list[_SwitchCommandBranch] = []
    pending_patterns: list[str | None] = []
    for index in range(0, len(branch_words), 2):
        pending_patterns.append(word_static_text(branch_words[index]))
        body_text = word_static_text(branch_words[index + 1])
        if body_text is None:
            return ()
        if body_text == '-':
            continue
        branches.append(_SwitchCommandBranch(tuple(pending_patterns), body_text))
        pending_patterns = []

    if pending_patterns:
        return ()
    return tuple(branches)


def _switch_branch_matched_values(
    current_values: tuple[str, ...],
    patterns: tuple[str | None, ...],
    match_mode: str,
) -> tuple[str, ...]:
    if not patterns:
        return ()
    if 'default' in patterns:
        return current_values

    branch_values = _switch_pattern_exact_values(patterns, match_mode)
    if not branch_values:
        return ()
    return tuple(value for value in current_values if value in branch_values)


def _embedded_script_result_values(
    text: str,
    state: VariableFlowState,
) -> tuple[str, ...]:
    diagnostics: list[Diagnostic] = []
    script = _FLOW_PARSER.parse_embedded_script_for_analysis(
        'file:///flow_expr.tcl',
        text,
        _ZERO_POSITION,
        diagnostics=diagnostics,
    )
    if diagnostics:
        return ()
    return _script_result_values(script, state)


def _script_result_values(
    script: Script,
    state: VariableFlowState,
) -> tuple[str, ...]:
    if len(script.commands) != 1:
        return ()
    command = script.commands[0]
    if not command.words:
        return ()

    command_name = word_static_text(command.words[0])
    match command_name:
        case 'concat' if len(command.words) == 2:
            return exact_word_values(command.words[1], state)
        case 'set':
            match len(command.words):
                case 2:
                    target_name = _simple_var_name(command.words[1])
                    if target_name is None:
                        return ()
                    return state.exact_values(target_name)
                case 3:
                    return exact_word_values(command.words[2], state)
                case _:
                    pass
        case 'switch':
            return _switch_command_values(command, state)
        case 'expr' if len(command.words) == 2:
            expr_text = word_static_text(command.words[1])
            if expr_text is None:
                return ()
            return eval_expr_text(state, expr_text, _embedded_script_result_values).values
        case _:
            return ()

    return ()
