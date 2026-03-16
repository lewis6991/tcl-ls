from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.facts.parsing import (
    ConditionVariableSubstitution,
    ListItem,
    scan_static_tcl_substitutions,
    split_tcl_list,
)
from tcl_lsp.analysis.facts.utils import (
    body_span,
    command_documentation,
    normalize_command_name,
)
from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import (
    BracedWord,
    Command,
    CommandSubstitution,
    LiteralText,
    ParseResult,
    QuotedWord,
    Script,
    VariableSubstitution,
    Word,
)


@dataclass(frozen=True, slots=True)
class LoweredScript:
    commands: tuple[LoweredCommand, ...]


@dataclass(frozen=True, slots=True)
class LoweredScriptBody:
    script: LoweredScript


@dataclass(frozen=True, slots=True)
class LoweredWordReferences:
    variable_substitutions: tuple[VariableSubstitution, ...]
    command_substitutions: tuple[LoweredScript, ...]


@dataclass(frozen=True, slots=True)
class LoweredCondition:
    variable_substitutions: tuple[ConditionVariableSubstitution, ...]
    command_substitutions: tuple[LoweredScript, ...]


@dataclass(frozen=True, slots=True)
class LoweredIfClause:
    condition: LoweredCondition | None
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredCommandBase:
    command: Command
    command_name: str | None
    word_references: tuple[LoweredWordReferences, ...]


@dataclass(frozen=True, slots=True)
class LoweredGenericCommand(LoweredCommandBase):
    pass


@dataclass(frozen=True, slots=True)
class LoweredProcCommand(LoweredCommandBase):
    name: str | None
    name_span: Span | None
    documentation: str | None
    parameter_items: tuple[ListItem, ...]
    body_span: Span | None
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredNamespaceEvalCommand(LoweredCommandBase):
    namespace_name: str | None
    namespace_span: Span | None
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredForeachCommand(LoweredCommandBase):
    variable_items: tuple[ListItem, ...]
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredLmapCommand(LoweredCommandBase):
    variable_items: tuple[ListItem, ...]
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredForCommand(LoweredCommandBase):
    start_body: LoweredScriptBody | None
    condition: LoweredCondition | None
    next_body: LoweredScriptBody | None
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredIfCommand(LoweredCommandBase):
    clauses: tuple[LoweredIfClause, ...]
    else_body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredCatchCommand(LoweredCommandBase):
    body: LoweredScriptBody | None


@dataclass(frozen=True, slots=True)
class LoweredSwitchCommand(LoweredCommandBase):
    regexp_binding_words: tuple[Word, ...]
    branch_bodies: tuple[LoweredScriptBody, ...]


@dataclass(frozen=True, slots=True)
class LoweredWhileCommand(LoweredCommandBase):
    condition: LoweredCondition | None
    body: LoweredScriptBody | None


type LoweredCommand = LoweredCommandBase

_EMPTY_LOWERED_WORD_REFERENCES = LoweredWordReferences(
    variable_substitutions=(),
    command_substitutions=(),
)


def _braced_word_raw_content(word: BracedWord) -> str:
    raw_text = word.raw_text
    if raw_text.startswith('{'):
        raw_text = raw_text[1:]
    if raw_text.endswith('}'):
        raw_text = raw_text[:-1]
    return raw_text


def _script_lexical_spans(
    script: Script,
    *,
    parser: Parser,
    source_id: str,
) -> tuple[tuple[Span, ...], tuple[Span, ...]]:
    string_spans: list[Span] = []
    operator_spans: list[Span] = []
    for command in script.commands:
        for word in command.words:
            _collect_word_lexical_spans(
                word,
                parser=parser,
                source_id=source_id,
                string_spans=string_spans,
                operator_spans=operator_spans,
            )
    return tuple(string_spans), tuple(operator_spans)


def _collect_word_lexical_spans(
    word: Word,
    *,
    parser: Parser,
    source_id: str,
    string_spans: list[Span],
    operator_spans: list[Span],
) -> None:
    if isinstance(word, BracedWord):
        if not word.expanded:
            operator_spans.append(Span(start=word.span.start, end=word.content_span.start))
            operator_spans.append(Span(start=word.content_span.end, end=word.span.end))
            if any(char in word.text for char in '{}[]"'):
                nested_parse_result = parser.parse_embedded_script(
                    source_id=source_id,
                    text=_braced_word_raw_content(word),
                    start_position=word.content_span.start,
                )
                nested_strings, nested_operators = _script_lexical_spans(
                    nested_parse_result.script,
                    parser=parser,
                    source_id=source_id,
                )
                string_spans.extend(nested_strings)
                operator_spans.extend(nested_operators)
        return

    if isinstance(word, QuotedWord):
        string_spans.append(Span(start=word.span.start, end=word.content_span.start))
        string_spans.append(Span(start=word.content_span.end, end=word.span.end))

    for part in word.parts:
        if isinstance(part, LiteralText):
            if isinstance(word, QuotedWord):
                string_spans.append(part.span)
            continue
        if isinstance(part, VariableSubstitution):
            _collect_variable_substitution_lexical_spans(
                part,
                operator_spans=operator_spans,
            )
            continue
        _collect_command_substitution_lexical_spans(
            part,
            parser=parser,
            source_id=source_id,
            string_spans=string_spans,
            operator_spans=operator_spans,
        )


def _collect_command_substitution_lexical_spans(
    substitution: CommandSubstitution,
    *,
    parser: Parser,
    source_id: str,
    string_spans: list[Span],
    operator_spans: list[Span],
) -> None:
    operator_spans.append(Span(start=substitution.span.start, end=substitution.content_span.start))
    operator_spans.append(Span(start=substitution.content_span.end, end=substitution.span.end))
    nested_strings, nested_operators = _script_lexical_spans(
        substitution.script,
        parser=parser,
        source_id=source_id,
    )
    string_spans.extend(nested_strings)
    operator_spans.extend(nested_operators)


def _collect_variable_substitution_lexical_spans(
    substitution: VariableSubstitution,
    *,
    operator_spans: list[Span],
) -> None:
    if not substitution.brace_wrapped:
        return

    opening_brace_start = substitution.span.start.advance('$')
    opening_brace_end = opening_brace_start.advance('{')
    closing_brace_start = opening_brace_end.advance(substitution.name)
    operator_spans.append(Span(start=opening_brace_start, end=opening_brace_end))
    operator_spans.append(Span(start=closing_brace_start, end=substitution.span.end))


@dataclass(frozen=True, slots=True)
class LoweringResult:
    script: LoweredScript
    diagnostics: tuple[Diagnostic, ...]
    comment_spans: tuple[Span, ...]
    string_spans: tuple[Span, ...]
    operator_spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class _SwitchLayout:
    branch_list_word: Word | None
    branch_words: tuple[Word, ...]
    regexp_binding_words: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class _SwitchOptionState:
    value_index: int
    regexp_binding_words: tuple[Word, ...]


def lower_parse_result(
    parse_result: ParseResult,
    *,
    parser: Parser,
    collect_lexical_spans: bool = True,
) -> LoweringResult:
    lowering_result = lower_script(
        parse_result.script,
        parser=parser,
        source_id=parse_result.source_id,
        collect_lexical_spans=collect_lexical_spans,
    )
    return LoweringResult(
        script=lowering_result.script,
        diagnostics=lowering_result.diagnostics,
        comment_spans=(
            tuple(token.span for token in parse_result.tokens if token.kind == 'comment')
            + lowering_result.comment_spans
            if collect_lexical_spans
            else ()
        ),
        string_spans=lowering_result.string_spans,
        operator_spans=lowering_result.operator_spans,
    )


def lower_script(
    script: Script,
    *,
    parser: Parser,
    source_id: str,
    collect_lexical_spans: bool = True,
) -> LoweringResult:
    lowerer = _Lowerer(
        parser=parser,
        source_id=source_id,
        collect_lexical_spans=collect_lexical_spans,
    )
    string_spans: tuple[Span, ...] = ()
    operator_spans: tuple[Span, ...] = ()
    if collect_lexical_spans:
        string_spans, operator_spans = _script_lexical_spans(
            script,
            parser=parser,
            source_id=source_id,
        )
    return LoweringResult(
        script=lowerer.lower_script(script),
        diagnostics=tuple(lowerer.diagnostics),
        comment_spans=tuple(lowerer.comment_spans),
        string_spans=string_spans + tuple(lowerer.string_spans),
        operator_spans=operator_spans + tuple(lowerer.operator_spans),
    )


class _Lowerer:
    __slots__ = (
        '_collect_lexical_spans',
        '_parser',
        '_source_id',
        'comment_spans',
        'diagnostics',
        'operator_spans',
        'string_spans',
    )

    def __init__(
        self,
        *,
        parser: Parser,
        source_id: str,
        collect_lexical_spans: bool,
    ) -> None:
        self._collect_lexical_spans = collect_lexical_spans
        self._parser = parser
        self._source_id = source_id
        self.diagnostics: list[Diagnostic] = []
        self.comment_spans: list[Span] = []
        self.string_spans: list[Span] = []
        self.operator_spans: list[Span] = []

    def lower_script(self, script: Script) -> LoweredScript:
        return LoweredScript(
            commands=tuple(self._lower_command(command) for command in script.commands)
        )

    def _lower_command(self, command: Command) -> LoweredCommand:
        words = command.words
        if not words:
            return LoweredGenericCommand(
                command=command,
                command_name=None,
                word_references=(),
            )

        command_name = word_static_text(words[0])
        word_references = tuple(self._lower_word_references(word) for word in words)
        dispatch_name = normalize_command_name(command_name) if command_name is not None else None
        if dispatch_name == 'proc':
            return self._lower_proc(command, command_name, word_references)
        if dispatch_name == 'namespace':
            return self._lower_namespace(command, command_name, word_references)
        if dispatch_name == 'foreach':
            return self._lower_foreach(command, command_name, word_references)
        if dispatch_name == 'lmap':
            return self._lower_lmap(command, command_name, word_references)
        if dispatch_name == 'for':
            return self._lower_for(command, command_name, word_references)
        if dispatch_name == 'if':
            return self._lower_if(command, command_name, word_references)
        if dispatch_name == 'catch':
            return self._lower_catch(command, command_name, word_references)
        if dispatch_name == 'switch':
            return self._lower_switch(command, command_name, word_references)
        if dispatch_name == 'while':
            return self._lower_while(command, command_name, word_references)
        return LoweredGenericCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
        )

    def _lower_proc(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        name_word = command.words[1] if len(command.words) > 1 else None
        body_word = command.words[3] if len(command.words) > 3 else None
        return LoweredProcCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            name=word_static_text(name_word) if name_word is not None else None,
            name_span=name_word.span if name_word is not None else None,
            documentation=command_documentation(command),
            parameter_items=self._parse_list_items(
                command.words[2] if len(command.words) > 2 else None
            ),
            body_span=body_span(body_word) if body_word is not None else None,
            body=self._lower_script_word(body_word),
        )

    def _lower_namespace(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        if len(command.words) < 2 or word_static_text(command.words[1]) != 'eval':
            return LoweredGenericCommand(
                command=command,
                command_name=command_name,
                word_references=word_references,
            )
        namespace_word = command.words[2] if len(command.words) > 2 else None
        return LoweredNamespaceEvalCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            namespace_name=word_static_text(namespace_word) if namespace_word is not None else None,
            namespace_span=namespace_word.span if namespace_word is not None else None,
            body=self._lower_script_word(command.words[3] if len(command.words) > 3 else None),
        )

    def _lower_foreach(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        return LoweredForeachCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            variable_items=self._lower_loop_variable_items(command),
            body=self._lower_script_word(command.words[-1] if len(command.words) > 3 else None),
        )

    def _lower_lmap(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        return LoweredLmapCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            variable_items=self._lower_loop_variable_items(command),
            body=self._lower_script_word(command.words[-1] if len(command.words) > 3 else None),
        )

    def _lower_for(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        return LoweredForCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            start_body=self._lower_script_word(
                command.words[1] if len(command.words) > 1 else None
            ),
            condition=self._lower_condition_word(
                command.words[2] if len(command.words) > 2 else None
            ),
            next_body=self._lower_script_word(command.words[3] if len(command.words) > 3 else None),
            body=self._lower_script_word(command.words[4] if len(command.words) > 4 else None),
        )

    def _lower_if(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        clauses: list[LoweredIfClause] = []
        else_body: LoweredScriptBody | None = None

        index = 1
        while index < len(command.words):
            clause_kind = 'if'
            clause_span = command.span
            if clauses:
                keyword_word = command.words[index]
                keyword = word_static_text(keyword_word)
                if keyword == 'elseif':
                    clause_kind = 'elseif'
                    clause_span = keyword_word.span
                    index += 1
                elif keyword == 'else':
                    clause_span = keyword_word.span
                    if index + 1 >= len(command.words):
                        self._emit_analysis_diagnostic(
                            code='malformed-if',
                            message='Malformed `if` command; `else` requires a body.',
                            span=clause_span,
                        )
                        break
                    else_body = self._lower_script_word(
                        command.words[index + 1] if index + 1 < len(command.words) else None
                    )
                    if index + 2 < len(command.words):
                        self._emit_analysis_diagnostic(
                            code='malformed-if',
                            message='Malformed `if` command; trailing words after `else` body.',
                            span=command.words[index + 2].span,
                        )
                    break
                elif keyword is not None:
                    self._emit_analysis_diagnostic(
                        code='malformed-if',
                        message=(
                            f'Malformed `if` command; expected `elseif` or `else`, got `{keyword}`.'
                        ),
                        span=keyword_word.span,
                    )
                    break
                else:
                    break

            condition = self._lower_condition_word(
                command.words[index] if index < len(command.words) else None
            )
            body_index = self._if_body_index(command.words, index + 1)
            if body_index is None:
                if clause_kind == 'elseif':
                    self._emit_analysis_diagnostic(
                        code='malformed-if',
                        message='Malformed `if` command; `elseif` requires a test and body.',
                        span=clause_span,
                    )
                break

            clauses.append(
                LoweredIfClause(
                    condition=condition,
                    body=self._lower_script_word(command.words[body_index]),
                )
            )
            index = body_index + 1

        return LoweredIfCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            clauses=tuple(clauses),
            else_body=else_body,
        )

    def _lower_catch(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        return LoweredCatchCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            body=self._lower_script_word(command.words[1] if len(command.words) > 1 else None),
        )

    def _lower_switch(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        layout = self._switch_layout(command.words)
        if layout is None:
            return LoweredSwitchCommand(
                command=command,
                command_name=command_name,
                word_references=word_references,
                regexp_binding_words=(),
                branch_bodies=(),
            )

        if layout.branch_list_word is not None:
            branch_bodies = self._lower_switch_branch_list(layout.branch_list_word)
        else:
            branch_bodies = self._lower_switch_branch_words(layout.branch_words)

        return LoweredSwitchCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            regexp_binding_words=layout.regexp_binding_words,
            branch_bodies=branch_bodies,
        )

    def _lower_while(
        self,
        command: Command,
        command_name: str | None,
        word_references: tuple[LoweredWordReferences, ...],
    ) -> LoweredCommand:
        return LoweredWhileCommand(
            command=command,
            command_name=command_name,
            word_references=word_references,
            condition=self._lower_condition_word(
                command.words[1] if len(command.words) > 1 else None
            ),
            body=self._lower_script_word(command.words[2] if len(command.words) > 2 else None),
        )

    def _lower_condition_word(self, word: Word | None) -> LoweredCondition | None:
        if not isinstance(word, BracedWord) or word.expanded:
            return None

        variable_substitutions: list[ConditionVariableSubstitution] = []
        command_substitutions: list[LoweredScript] = []
        for substitution in scan_static_tcl_substitutions(
            _braced_word_raw_content(word),
            word.content_span.start,
        ):
            if isinstance(substitution, ConditionVariableSubstitution):
                variable_substitutions.append(substitution)
                continue
            command_substitutions.append(
                self._lower_embedded_script(substitution.text, substitution.content_span.start)
            )

        return LoweredCondition(
            variable_substitutions=tuple(variable_substitutions),
            command_substitutions=tuple(command_substitutions),
        )

    def _lower_script_word(self, word: Word | None) -> LoweredScriptBody | None:
        if word is None:
            return None
        if isinstance(word, BracedWord) and not word.expanded:
            return LoweredScriptBody(
                script=self._lower_embedded_script(
                    _braced_word_raw_content(word),
                    word.content_span.start,
                )
            )
        text = word_static_text(word)
        if text is None:
            return None
        return LoweredScriptBody(script=self._lower_embedded_script(text, word.content_span.start))

    def _lower_embedded_script(self, text: str, start_position: Position) -> LoweredScript:
        if not self._collect_lexical_spans:
            script = self._parser.parse_embedded_script_for_analysis(
                source_id=self._source_id,
                text=text,
                start_position=start_position,
                diagnostics=self.diagnostics,
            )
            lowering_result = lower_script(
                script,
                parser=self._parser,
                source_id=self._source_id,
                collect_lexical_spans=False,
            )
            self.diagnostics.extend(lowering_result.diagnostics)
            return lowering_result.script

        parse_result = self._parser.parse_embedded_script(
            source_id=self._source_id,
            text=text,
            start_position=start_position,
        )
        lowering_result = lower_parse_result(
            parse_result,
            parser=self._parser,
            collect_lexical_spans=True,
        )
        self.diagnostics.extend(parse_result.diagnostics)
        self.diagnostics.extend(lowering_result.diagnostics)
        self.comment_spans.extend(lowering_result.comment_spans)
        self.string_spans.extend(lowering_result.string_spans)
        self.operator_spans.extend(lowering_result.operator_spans)
        return lowering_result.script

    def _lower_word_references(self, word: Word) -> LoweredWordReferences:
        if isinstance(word, BracedWord):
            return _EMPTY_LOWERED_WORD_REFERENCES

        if len(word.parts) == 1 and isinstance(word.parts[0], LiteralText):
            return _EMPTY_LOWERED_WORD_REFERENCES

        variable_substitutions: list[VariableSubstitution] = []
        command_substitutions: list[LoweredScript] = []
        for part in word.parts:
            if isinstance(part, VariableSubstitution):
                variable_substitutions.append(part)
                continue
            if isinstance(part, CommandSubstitution):
                command_substitutions.append(self.lower_script(part.script))

        return LoweredWordReferences(
            variable_substitutions=tuple(variable_substitutions),
            command_substitutions=tuple(command_substitutions),
        )

    def _parse_list_items(self, word: Word | None) -> tuple[ListItem, ...]:
        if word is None:
            return ()
        if isinstance(word, BracedWord) and not word.expanded:
            return tuple(split_tcl_list(word.text, word.content_span.start))
        static_text = word_static_text(word)
        if static_text is None:
            return ()
        return tuple(split_tcl_list(static_text, word.content_span.start))

    def _lower_loop_variable_items(self, command: Command) -> tuple[ListItem, ...]:
        items: list[ListItem] = []
        for index in range(1, len(command.words) - 2, 2):
            items.extend(self._parse_list_items(command.words[index]))
        return tuple(items)

    def _if_body_index(self, words: tuple[Word, ...], index: int) -> int | None:
        if index < len(words) and word_static_text(words[index]) == 'then':
            index += 1
        if index >= len(words):
            return None
        return index

    def _switch_layout(self, words: tuple[Word, ...]) -> _SwitchLayout | None:
        if len(words) < 3:
            if len(words) >= 1:
                self._emit_analysis_diagnostic(
                    code='malformed-switch',
                    message='Malformed `switch` command; missing pattern/body clauses.',
                    span=words[0].span,
                )
            return None

        option_state = self._scan_switch_options(words)
        if option_state is None:
            return None
        if option_state.value_index >= len(words):
            self._emit_analysis_diagnostic(
                code='malformed-switch',
                message='Malformed `switch` command; missing value to match.',
                span=words[0].span,
            )
            return None

        branch_words = tuple(words[option_state.value_index + 1 :])
        if not branch_words:
            self._emit_analysis_diagnostic(
                code='malformed-switch',
                message='Malformed `switch` command; missing pattern/body clauses.',
                span=words[option_state.value_index].span,
            )
            return None

        if len(branch_words) == 1:
            return _SwitchLayout(
                branch_list_word=branch_words[0],
                branch_words=(),
                regexp_binding_words=option_state.regexp_binding_words,
            )

        return _SwitchLayout(
            branch_list_word=None,
            branch_words=branch_words,
            regexp_binding_words=option_state.regexp_binding_words,
        )

    def _lower_switch_branch_list(self, word: Word) -> tuple[LoweredScriptBody, ...]:
        items = self._parse_list_items(word)
        if len(items) % 2 != 0:
            self._emit_analysis_diagnostic(
                code='malformed-switch',
                message='Malformed `switch` command; branch lists require pattern/body pairs.',
                span=word.span,
            )
            return ()

        bodies: list[LoweredScriptBody] = []
        for index in range(1, len(items), 2):
            body_item = items[index]
            if body_item.text == '-':
                continue
            bodies.append(
                LoweredScriptBody(
                    script=self._lower_embedded_script(body_item.text, body_item.content_start)
                )
            )
        return tuple(bodies)

    def _lower_switch_branch_words(
        self,
        branch_words: tuple[Word, ...],
    ) -> tuple[LoweredScriptBody, ...]:
        if len(branch_words) % 2 != 0:
            self._emit_analysis_diagnostic(
                code='malformed-switch',
                message='Malformed `switch` command; branches require pattern/body pairs.',
                span=branch_words[-1].span,
            )
            return ()

        bodies: list[LoweredScriptBody] = []
        for index in range(1, len(branch_words), 2):
            body_word = branch_words[index]
            if word_static_text(body_word) == '-':
                continue
            lowered_body = self._lower_script_word(body_word)
            if lowered_body is not None:
                bodies.append(lowered_body)
        return tuple(bodies)

    def _scan_switch_options(self, words: tuple[Word, ...]) -> _SwitchOptionState | None:
        index = 1
        regexp_binding_words: list[Word] = []
        regexp_mode = False

        while index < len(words):
            option = word_static_text(words[index])
            if option is None:
                break
            if option == '--':
                index += 1
                break
            if option in {'-exact', '-glob', '-nocase'}:
                index += 1
                continue
            if option == '-regexp':
                regexp_mode = True
                index += 1
                continue
            if option in {'-matchvar', '-indexvar'}:
                if index + 1 >= len(words):
                    self._emit_analysis_diagnostic(
                        code='malformed-switch',
                        message=f'Malformed `switch` command; `{option}` requires a value.',
                        span=words[index].span,
                    )
                    return None
                if regexp_mode:
                    regexp_binding_words.append(words[index + 1])
                index += 2
                continue
            if option.startswith('-') and option != '-':
                self._emit_analysis_diagnostic(
                    code='malformed-switch',
                    message=f'Malformed `switch` command; unknown option `{option}`.',
                    span=words[index].span,
                )
                return None
            break

        return _SwitchOptionState(
            value_index=index,
            regexp_binding_words=tuple(regexp_binding_words),
        )

    def _emit_analysis_diagnostic(self, *, code: str, message: str, span: Span) -> None:
        self.diagnostics.append(
            Diagnostic(
                span=span,
                severity='error',
                message=message,
                source='analysis',
                code=code,
            )
        )
