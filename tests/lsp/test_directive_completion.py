from __future__ import annotations

from pathlib import Path
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
    completion_items,
    open_server_document,
)


def _items(
    server: LanguageServer, marked_text: str, *, uri: str = MAIN_URI
) -> tuple[str, list[dict[str, object]]]:
    before, after = marked_text.split('|')
    text = before + after
    open_server_document(server, text, uri=uri)
    line = before.count('\n')
    character = len(before.rsplit('\n', 1)[-1].encode('utf-16-le')) // 2
    return text, completion_items(server, uri=uri, line=line, character=character)


def _apply_completion(text: str, item: dict[str, object]) -> str:
    edit = as_dict(item['textEdit'])
    edit_range = as_dict(edit['range'])
    positions: list[int] = []
    for edge in ('start', 'end'):
        raw = as_dict(edit_range[edge])
        position = PositionCodec().position_from_client_units(
            text.splitlines(keepends=True),
            types.Position(cast(int, raw['line']), cast(int, raw['character'])),
        )
        offset = offset_at_position(text, position.line, position.character)
        assert offset is not None
        positions.append(offset)
    return text[: positions[0]] + cast(str, edit['newText']) + text[positions[1] :]


@pytest.mark.parametrize(
    ('marked_text', 'labels'),
    [
        ('# |', ['tcl-ls:']),
        ('# tcl-|', ['tcl-ls:']),
        ('# tcl-ls: |', ['diagnostic', 'diagnostic-file', 'module']),
        ('# tcl-ls: diag|', ['diagnostic', 'diagnostic-file']),
        ('# tcl-ls: diagnostic-|', ['diagnostic-file']),
        (
            '# tcl-ls: diagnostic invalid-expr |',
            ['default', 'error', 'hint', 'information', 'off', 'warning'],
        ),
        ('# tcl-ls: diagnostic invalid-expr o|', ['off']),
        (
            '# tcl-ls: diagnostic-file invalid-expr |',
            ['default', 'error', 'hint', 'information', 'off', 'warning'],
        ),
        ('# tcl-ls: diagnostic-file invalid-expr o|', ['off']),
        ('# tcl-ls: diagnostic-file invalid-expr off |', []),
        ('# tcl-ls: diagnostic invalid-expr off |', []),
        ('# tcl-ls: diagnostic invalid-expr off -s|', []),
        ('# tcl-ls: diagnostic invalid-expr off -scope |', []),
        ('# tcl-ls: diagnostic invalid-expr off -scope f|', []),
        ('# tcl-ls: diagnostic invalid-expr off -scope file |', []),
        ('# tcl-ls: diagnostic invalid-expr bad-level |', []),
        ('# tcl-ls: diagnostic invalid-expr off -path |', []),
    ],
)
def test_completion_offers_values_for_the_current_directive_argument(
    server: LanguageServer, marked_text: str, labels: list[str]
) -> None:
    _, items = _items(server, marked_text)
    assert [item['label'] for item in items] == labels


@pytest.mark.parametrize('directive', ['diagnostic', 'diagnostic-file'])
def test_diagnostic_code_completion_has_descriptions_and_parser_codes(
    server: LanguageServer,
    directive: str,
) -> None:
    _, items = _items(server, f'# tcl-ls: {directive} |')
    by_label = {item['label']: item for item in items}
    assert {
        '*',
        'invalid-expr',
        'invalid-value',
        'unmatched-brace',
        'unresolved-command',
    } <= by_label.keys()
    assert 'off' not in by_label
    assert 'command' not in by_label
    assert as_dict(by_label['invalid-expr']['documentation']) == {
        'kind': 'plaintext',
        'value': 'An expression has invalid syntax.',
    }


@pytest.mark.parametrize('directive', ['diagnostic', 'diagnostic-file'])
def test_completion_replaces_a_whole_hyphenated_code_mid_word(
    server: LanguageServer, directive: str
) -> None:
    text, items = _items(
        server,
        f'# tcl-ls: {directive} inv|alid-expr-operand off\nexpr {{1 +}}\n',
    )
    item = next(item for item in items if item['label'] == 'invalid-expr')
    updated = _apply_completion(text, item)
    assert updated == f'# tcl-ls: {directive} invalid-expr off\nexpr {{1 +}}\n'
    open_server_document(server, updated, version=2)
    assert server.documents[MAIN_URI].analysis.diagnostics == ()


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_completion_works_in_indented_procedure_comments(
    server: LanguageServer, newline: str
) -> None:
    text, items = _items(
        server, newline.join(['proc run {} {', '\t# tcl-ls: diagnostic unmatched-bra|', '}', ''])
    )
    assert [item['label'] for item in items] == ['unmatched-brace', 'unmatched-bracket']
    updated = _apply_completion(text, items[0])
    assert updated == text.replace('unmatched-bra', 'unmatched-brace')


@pytest.mark.parametrize(
    'marked_text',
    [
        'set data {# tcl-ls: diagnostic inv|}\n',
        'puts "# tcl-ls: diagnostic inv|"\n',
        'proc run {} {\n    set data {# tcl-ls: diagnostic inv|}\n}\n',
        '# Other prose: tcl-ls: diagnostic inv|\n',
        '# Other prose \\\n# tcl-ls: diagnostic inv|\n',
    ],
)
def test_directive_completion_does_not_treat_data_or_prose_as_directives(
    server: LanguageServer, marked_text: str
) -> None:
    _, items = _items(server, marked_text)
    assert items == []


def test_directive_completion_works_in_metadata_defined_bodies(
    server: LanguageServer, tmp_path: Path
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command script {body} {enter tcl body 1}}\n'
    )
    _, items = _items(
        server,
        'script {\n    # tcl-ls: diagnostic inv|\n}\n',
        uri=(tmp_path / 'main.tcl').as_uri(),
    )
    assert 'invalid-expr' in {item['label'] for item in items}


def test_completion_tracks_directives_in_relocated_cached_bodies(server: LanguageServer) -> None:
    original = 'proc run {} {\n    # tcl-ls: diagnostic inv\n}\n'
    open_server_document(server, original)
    updated = '# Added header\n' + original
    open_server_document(server, updated, version=2)
    items = completion_items(server, line=2, character=len('    # tcl-ls: diagnostic inv'))
    assert 'invalid-expr' in {item['label'] for item in items}


def test_completion_uses_pending_buffer_text(
    server: LanguageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leave_pending(*, uri: str, version: int) -> None:
        del uri, version

    open_server_document(server, '# An ordinary comment\n')
    monkeypatch.setattr(server, 'schedule_document_change', leave_pending)
    text = '# tcl-ls: diagnostic inv'
    change_server_document(server, text)
    items = completion_items(server, line=0, character=len(text))
    assert 'invalid-expr' in {item['label'] for item in items}


def test_completion_edits_use_client_units_after_non_ascii_text(server: LanguageServer) -> None:
    text, items = _items(server, 'puts 🙂; # tcl-ls: diagnostic inv|alid-expr-operand off\n')
    item = next(item for item in items if item['label'] == 'invalid-expr')
    assert _apply_completion(text, item) == 'puts 🙂; # tcl-ls: diagnostic invalid-expr off\n'


def test_module_directive_completion_offers_loaded_modules(server: LanguageServer) -> None:
    _, items = _items(server, '# tcl-ls: module Tcl|')
    assert {'Tcl', 'TclOO'} <= {item['label'] for item in items}
