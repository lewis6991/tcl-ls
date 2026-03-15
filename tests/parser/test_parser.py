from __future__ import annotations

from tcl_lsp.common import Position
from tcl_lsp.parser import (
    BareWord,
    CommandSubstitution,
    Parser,
    VariableSubstitution,
    word_static_text,
)


def test_parser_builds_commands_and_nested_substitutions() -> None:
    parser = Parser()
    result = parser.parse_document(
        'test.tcl',
        '# comment\nset value [greet $name]\nputs "Hello, $name"\n',
    )

    assert result.diagnostics == ()
    assert [token.kind for token in result.tokens if token.kind == 'comment'] == ['comment']
    assert len(result.script.commands) == 2

    set_command = result.script.commands[0]
    assert [word_static_text(word) for word in set_command.words] == ['set', 'value', None]

    substitution_word = set_command.words[2]
    assert isinstance(substitution_word, BareWord)
    assert substitution_word.parts
    command_part = substitution_word.parts[0]
    assert isinstance(command_part, CommandSubstitution)
    nested_command = command_part.script.commands[0]
    assert [word_static_text(word) for word in nested_command.words] == ['greet', None]
    nested_variable_word = nested_command.words[1]
    assert isinstance(nested_variable_word, BareWord)
    nested_variable = nested_variable_word.parts[0]
    assert isinstance(nested_variable, VariableSubstitution)
    assert nested_variable.name == 'name'


def test_parser_reports_unmatched_constructs() -> None:
    parser = Parser()
    result = parser.parse_document(
        'broken.tcl',
        'puts "unterminated\nset value [greet $name\nset other ${missing\n',
    )

    diagnostic_codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert 'unmatched-quote' in diagnostic_codes
    assert 'unmatched-bracket' in diagnostic_codes
    assert 'malformed-variable' in diagnostic_codes


def test_parse_embedded_script_preserves_absolute_positions() -> None:
    parser = Parser()
    result = parser.parse_embedded_script(
        'embedded.tcl',
        'puts $name',
        Position(offset=20, line=4, character=6),
    )

    variable_word = result.script.commands[0].words[1]
    assert isinstance(variable_word, BareWord)
    variable = variable_word.parts[0]
    assert isinstance(variable, VariableSubstitution)
    assert variable.span.start.offset == 25
    assert variable.span.start.line == 4
    assert variable.span.start.character == 11
