from __future__ import annotations

from tcl_lsp.common import Position
from tcl_lsp.parser import (
    BareWord,
    CommandSubstitution,
    Parser,
    QuotedWord,
    VariableSubstitution,
    word_static_text,
)


def test_parser_builds_commands_and_nested_substitutions(parser: Parser) -> None:
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


def test_parser_attaches_contiguous_leading_comment_blocks_to_commands(parser: Parser) -> None:
    result = parser.parse_document(
        'comments.tcl',
        '# first line\n'
        '# second line\n'
        'proc greet {} {return ok}\n'
        '\n'
        '# detached\n'
        '\n'
        'proc skip {} {return ok}\n',
    )

    assert [comment.text for comment in result.script.commands[0].leading_comments] == [
        '# first line',
        '# second line',
    ]
    assert result.script.commands[1].leading_comments == ()


def test_parser_reports_unmatched_constructs(parser: Parser) -> None:
    result = parser.parse_document(
        'broken.tcl',
        'puts "unterminated\nset value [greet $name\nset other ${missing\n',
    )

    diagnostic_codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert 'unmatched-quote' in diagnostic_codes
    assert 'unmatched-bracket' in diagnostic_codes
    assert 'malformed-variable' in diagnostic_codes


def test_parse_embedded_script_preserves_absolute_positions(parser: Parser) -> None:
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


def test_parser_treats_invalid_variable_starters_as_literal_text(parser: Parser) -> None:
    result = parser.parse_document('literal-dollar.tcl', 'puts "```!@#$%^&*()"\nputs $@\nputs $\n')

    assert result.diagnostics == ()
    assert len(result.script.commands) == 3
    assert [word_static_text(word) for word in result.script.commands[0].words] == [
        'puts',
        '```!@#$%^&*()',
    ]
    assert [word_static_text(word) for word in result.script.commands[1].words] == ['puts', '$@']
    assert [word_static_text(word) for word in result.script.commands[2].words] == ['puts', '$']


def test_parser_stops_bare_variable_names_before_trailing_colons(parser: Parser) -> None:
    result = parser.parse_document('punctuated-vars.tcl', 'puts $argv0:\nputs "$pname:"\n')

    assert result.diagnostics == ()

    first_word = result.script.commands[0].words[1]
    assert isinstance(first_word, BareWord)
    first_variable = first_word.parts[0]
    assert isinstance(first_variable, VariableSubstitution)
    assert first_variable.name == 'argv0'

    second_word = result.script.commands[1].words[1]
    assert isinstance(second_word, QuotedWord)
    second_variable = second_word.parts[0]
    assert isinstance(second_variable, VariableSubstitution)
    assert second_variable.name == 'pname'


def test_parser_handles_line_continuations_in_comments_and_commands(parser: Parser) -> None:
    result = parser.parse_document(
        'continued.tcl',
        '# the next line will restart with tclsh wherever it is \\\n'
        'exec tclsh "$0" "$@"\n'
        'puts hello \\\n'
        '    world\n',
    )

    assert result.diagnostics == ()
    assert len(result.script.commands) == 1
    assert [word_static_text(word) for word in result.script.commands[0].words] == [
        'puts',
        'hello',
        'world',
    ]
