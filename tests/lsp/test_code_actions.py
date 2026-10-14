from __future__ import annotations

from typing import cast

import pytest
from lsprotocol import types
from pygls.workspace.position_codec import PositionCodec

from tcl_lsp.common import offset_at_position
from tcl_lsp.lsp import LanguageServer
from tests.lsp.helpers import (
    MAIN_URI,
    as_dict,
    change_server_document,
    open_server_document,
    server_workspace_request,
)
from tests.lsp_support import process_message


def _actions(
    server: LanguageServer,
    line: int,
    character: int = 0,
    *,
    end: tuple[int, int] | None = None,
    only: list[str] | None = None,
    diagnostics: list[dict[str, object]] | None = None,
    uri: str = MAIN_URI,
) -> list[dict[str, object]]:
    context: dict[str, object] = {'diagnostics': diagnostics or []}
    if only is not None:
        context['only'] = only
    response = server_workspace_request(
        server,
        method='textDocument/codeAction',
        params={
            'textDocument': {'uri': uri},
            'range': {
                'start': {'line': line, 'character': character},
                'end': {'line': end[0], 'character': end[1]}
                if end is not None
                else {'line': line, 'character': character},
            },
            'context': context,
        },
    )
    assert 'error' not in response
    return cast(list[dict[str, object]], response['result'])


def _apply_action(
    text: str,
    action: dict[str, object],
    *,
    encoding: types.PositionEncodingKind = types.PositionEncodingKind.Utf16,
) -> str:
    workspace_edit = as_dict(action['edit'])
    changes = as_dict(workspace_edit['changes'])
    edits = cast(list[dict[str, object]], changes[MAIN_URI])
    assert len(edits) == 1
    edit = edits[0]
    edit_range = as_dict(edit['range'])
    assert edit_range['start'] == edit_range['end']
    start = as_dict(edit_range['start'])
    position = PositionCodec(encoding).position_from_client_units(
        text.splitlines(keepends=True),
        types.Position(cast(int, start['line']), cast(int, start['character'])),
    )
    offset = offset_at_position(text, position.line, position.character)
    assert offset is not None
    return text[:offset] + cast(str, edit['newText']) + text[offset:]


def _codes(server: LanguageServer) -> list[str]:
    return [diagnostic.code for diagnostic in server.documents[MAIN_URI].analysis.diagnostics]


def test_suppression_actions_are_advertised_as_quick_fixes(server: LanguageServer) -> None:
    provider = server.server_capabilities.code_action_provider
    assert isinstance(provider, types.CodeActionOptions)
    assert provider.code_action_kinds == [types.CodeActionKind.QuickFix]


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_command_action_suppresses_one_code_in_one_nested_command(
    server: LanguageServer, newline: str
) -> None:
    text = newline.join(['proc run {} {', '\tmissing $unknown', '\tother_missing', '}', ''])
    open_server_document(server, text)

    actions = _actions(server, 1, 2)
    assert [action['title'] for action in actions] == [
        'Suppress unresolved-command for this command',
        'Suppress unresolved-command for this file',
    ]
    assert actions[0]['kind'] == 'quickfix'
    assert not actions[0].get('isPreferred')
    diagnostics = cast(list[dict[str, object]], actions[0]['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-command']

    updated = _apply_action(text, actions[0])
    assert updated == text.replace(
        '\tmissing',
        f'\t# tcl-ls: diagnostic unresolved-command off{newline}\tmissing',
        1,
    )
    open_server_document(server, updated, version=2)
    assert sorted(_codes(server)) == ['unresolved-command', 'unresolved-variable']


def test_file_action_preserves_shebang_and_other_diagnostic_codes(server: LanguageServer) -> None:
    text = '#!/usr/bin/env tclsh\nproc run {} {\nmissing $unknown\nother_missing\n}\n'
    open_server_document(server, text)
    updated = _apply_action(text, _actions(server, 2, 1)[1])

    assert updated == (
        '#!/usr/bin/env tclsh\n'
        '# tcl-ls: diagnostic-file unresolved-command off\n'
        'proc run {} {\nmissing $unknown\nother_missing\n}\n'
    )
    open_server_document(server, updated, version=2)
    assert _codes(server) == ['unresolved-variable']


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_file_action_follows_existing_file_rules(server: LanguageServer, newline: str) -> None:
    text = newline.join(['missing', '# tcl-ls: diagnostic-file * default', 'other_missing', ''])
    open_server_document(server, text)
    updated = _apply_action(text, _actions(server, 0, 1)[1])

    assert updated == newline.join(
        [
            'missing',
            '# tcl-ls: diagnostic-file * default',
            '# tcl-ls: diagnostic-file unresolved-command off',
            'other_missing',
            '',
        ]
    )
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


def test_command_action_overrides_existing_command_rule(server: LanguageServer) -> None:
    text = '# tcl-ls: diagnostic * default\nmissing\n'
    open_server_document(server, text)
    actions = _actions(server, 1, 1)

    # A file rule cannot override the explicit command rule.
    assert len(actions) == 1
    updated = _apply_action(text, actions[0])
    assert updated == text.replace(
        'missing', '# tcl-ls: diagnostic unresolved-command off\nmissing'
    )
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


@pytest.mark.parametrize(
    'text',
    [
        'missing\n# tcl-ls: diagnostic-file * default',
        'proc setup {} {\n    # tcl-ls: diagnostic-file * default\n}\nmissing\n',
    ],
)
def test_file_actions_work_with_trailing_or_relocated_body_directives(
    server: LanguageServer, text: str
) -> None:
    open_server_document(server, text)
    # Move an unchanged procedure body to exercise cached directive locations.
    text = '# Added header\n' + text
    open_server_document(server, text, version=2)
    actions = _actions(server, 0, end=(len(text.splitlines()), 0))
    action = next(
        action
        for action in actions
        if action['title'] == 'Suppress unresolved-command for this file'
    )
    updated = _apply_action(text, action)
    assert '# tcl-ls: diagnostic-file * default\n' in updated
    open_server_document(server, updated, version=3)
    assert _codes(server) == []


def test_outer_command_action_ignores_rules_on_other_commands(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'if {1} {\n    # tcl-ls: diagnostic * default\n    puts ok; missing\n}\n',
    )
    # The existing rule is on `puts`, not `missing`, so the outer command
    # can still suppress the diagnostic on the second command.
    actions = _actions(server, 2, 14)
    updated = _apply_action(server.documents[MAIN_URI].text, actions[0])
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


def test_actions_omit_suppressions_that_an_inline_rule_would_override(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'if {1} {\n    # tcl-ls: diagnostic * default\n    ; missing\n}\n',
    )
    assert _codes(server) == ['unresolved-command']
    assert _actions(server, 2, 7) == []


def test_command_action_suppresses_expression_diagnostics(server: LanguageServer) -> None:
    text = 'set a {a 1 2 3}\nexpr 1 + $a\n'
    open_server_document(server, text)
    actions = _actions(server, 1, end=(2, 0))
    action = next(
        action for action in actions if action['title'] == 'Suppress invalid-expr for this command'
    )
    updated = _apply_action(text, action)
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


@pytest.mark.parametrize(
    ('text', 'line', 'character', 'command'),
    [
        ('puts ok; missing\n', 0, 10, None),
        ('if {1} {missing}\n', 0, 10, 'if'),
        ('set value [missing]\n', 0, 12, 'set'),
        ('set value [\n    missing\n]\n', 1, 5, '    missing'),
        ('puts \\\n    [missing]\n', 1, 6, 'puts'),
    ],
)
def test_command_action_uses_a_safe_enclosing_command(
    server: LanguageServer, text: str, line: int, character: int, command: str | None
) -> None:
    open_server_document(server, text)
    actions = _actions(server, line, character)
    if command is None:
        assert [action['title'] for action in actions] == [
            'Suppress unresolved-command for this file'
        ]
    else:
        assert actions[0]['title'] == 'Suppress unresolved-command for this command'
        updated = _apply_action(text, actions[0])
        indentation = command[: len(command) - len(command.lstrip())]
        assert updated == text.replace(
            command,
            f'{indentation}# tcl-ls: diagnostic unresolved-command off\n{command}',
            1,
        )
        open_server_document(server, updated, version=2)
        assert 'unresolved-command' not in _codes(server)
        assert not any(
            code.startswith(('unmatched-', 'invalid-diagnostic')) for code in _codes(server)
        )


def test_actions_deduplicate_matching_diagnostics(server: LanguageServer) -> None:
    open_server_document(server, 'proc run {} {\nputs "$first $second"\nputs $third\n}\n')
    actions = _actions(server, 1, end=(2, 0))

    assert len(actions) == 2
    for action in actions:
        assert len(cast(list[object], action['diagnostics'])) == 2


@pytest.mark.parametrize('only', [['refactor'], ['source.fixAll'], [], ['quickfix.something']])
def test_actions_respect_kind_filters(server: LanguageServer, only: list[str]) -> None:
    open_server_document(server, 'missing\n')
    assert _actions(server, 0, only=only) == []


def test_actions_use_current_diagnostics_in_the_requested_range(server: LanguageServer) -> None:
    open_server_document(server, 'puts ok\nmissing\n')
    stale: dict[str, object] = {
        'range': {'start': {'line': 0, 'character': 0}, 'end': {'line': 0, 'character': 4}},
        'message': 'Stale diagnostic',
        'code': 'unresolved-command',
        'source': 'another-server',
    }
    assert _actions(server, 0, diagnostics=[stale]) == []
    assert len(_actions(server, 1, only=['quickfix'])) == 2
    assert _actions(server, 1, 7) == []  # The end of the diagnostic is exclusive.
    assert _actions(server, 0, uri='file:///not-open.tcl') == []


def test_actions_use_pending_buffer_changes(
    server: LanguageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leave_change_pending(*, uri: str, version: int) -> None:
        del uri, version

    open_server_document(server, 'missing\n')
    monkeypatch.setattr(server, 'schedule_document_change', leave_change_pending)
    change_server_document(server, 'puts ok\n')
    assert _actions(server, 0) == []


def test_actions_use_versioned_edits_when_supported(server: LanguageServer) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 0,
            'method': 'initialize',
            'params': {'capabilities': {'workspace': {'workspaceEdit': {'documentChanges': True}}}},
        },
    )
    open_server_document(server, 'missing\n', version=7)
    workspace_edit = as_dict(_actions(server, 0)[0]['edit'])
    assert 'changes' not in workspace_edit
    changes = cast(list[dict[str, object]], workspace_edit['documentChanges'])
    assert len(changes) == 1
    assert changes[0]['textDocument'] == {'uri': MAIN_URI, 'version': 7}


@pytest.mark.parametrize('encoding', list(types.PositionEncodingKind))
def test_file_action_uses_the_client_encoding_after_non_ascii_text(
    server: LanguageServer, encoding: types.PositionEncodingKind
) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 0,
            'method': 'initialize',
            'params': {'capabilities': {'general': {'positionEncodings': [encoding.value]}}},
        },
    )
    text = 'missing\nputs 🙂; # tcl-ls: diagnostic-file * default'
    open_server_document(server, text)
    updated = _apply_action(text, _actions(server, 0)[1], encoding=encoding)

    assert updated == text + '\n# tcl-ls: diagnostic-file unresolved-command off'
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


def test_action_range_uses_client_character_units(server: LanguageServer) -> None:
    text = 'proc run {} {puts "🙂🙂🙂🙂🙂🙂🙂🙂 $unknown"}\n'
    open_server_document(server, text)
    # UTF-16 counts each emoji as two code units. This cursor is on `unknown`.
    character = len(text[: text.index('unknown')].encode('utf-16-le')) // 2
    actions = _actions(server, 0, character)
    assert actions[0]['title'] == 'Suppress unresolved-variable for this command'
    updated = _apply_action(text, actions[0])
    open_server_document(server, updated, version=2)
    assert _codes(server) == []


def test_parser_diagnostics_can_be_suppressed(server: LanguageServer) -> None:
    text = 'set value {\n'
    open_server_document(server, text)
    actions = _actions(server, 0, end=(1, 0))
    action = next(
        action for action in actions if action['title'] == 'Suppress unmatched-brace for this file'
    )
    updated = _apply_action(text, action)
    open_server_document(server, updated, version=2)
    assert 'unmatched-brace' not in _codes(server)
