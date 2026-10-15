from pathlib import Path
from typing import Any, cast

import pytest

from tcl_lsp.lsp import LanguageServer
from tests.lsp.helpers import (
    open_server_document,
    server_position_request,
    server_workspace_request,
)


@pytest.mark.parametrize('method', ['definition', 'declaration', 'implementation'])
@pytest.mark.parametrize('line', [1, 2, 3])
def test_source_command_navigation_includes_metadata_but_implementation_does_not(
    server: LanguageServer, tmp_path: Path, method: str, line: int
) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'meta module Tcl {\n'
        '    meta command app::dispatch {command args} {call 1.. namespace ::}\n'
        '    meta command app::dispatch {}\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    text = (
        'namespace eval app {\n'
        '    proc dispatch {args} {}\n'
        '    dispatch puts hello\n'
        '    dispatch {puts} hello\n'
        '}\n'
    )
    source.write_text(text)
    open_server_document(server, text, uri=source.as_uri())

    response = server_position_request(
        server,
        method=f'textDocument/{method}',
        uri=source.as_uri(),
        line=line,
        character=text.splitlines()[line].index('dispatch') + 1,
    )
    locations = cast(list[dict[str, Any]], response['result'])
    expected = [(source.as_uri(), 1)]
    if method != 'implementation':
        expected.extend([(config.as_uri(), 1), (config.as_uri(), 2)])
    assert [(item['uri'], item['range']['start']['line']) for item in locations] == expected
    assert [item['range']['start']['character'] for item in locations] == (
        [9] if method == 'implementation' else [9, 17, 17]
    )


@pytest.mark.parametrize('method', ['definition', 'declaration'])
def test_source_navigation_uses_the_module_at_each_call(
    server: LanguageServer, tmp_path: Path, method: str
) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'meta module Alpha {meta command dispatch {args}}\n'
        'meta module Beta {meta override dispatch {args}}\n'
    )
    source = tmp_path / 'main.tcl'
    text = (
        'proc dispatch {args} {}\n'
        'dispatch\n'
        '# tcl-ls: module Alpha\n'
        'dispatch\n'
        'if {1} {\n'
        '    # tcl-ls: module Beta\n'
        '    dispatch\n'
        '}\n'
        'dispatch\n'
    )
    source.write_text(text)
    open_server_document(server, text, uri=source.as_uri())

    for line, metadata_line in [(1, None), (3, 0), (6, 1), (8, 0)]:
        response = server_position_request(
            server,
            method=f'textDocument/{method}',
            uri=source.as_uri(),
            line=line,
            character=text.splitlines()[line].index('dispatch') + 1,
        )
        locations = cast(list[dict[str, Any]], response['result'])
        expected = [(source.as_uri(), 0)]
        if metadata_line is not None:
            expected.append((config.as_uri(), metadata_line))
        assert [(item['uri'], item['range']['start']['line']) for item in locations] == expected


@pytest.mark.parametrize('method', ['definition', 'declaration'])
@pytest.mark.parametrize('prefix', ['', 'package require Library\n'])
def test_metadata_navigation_uses_qualified_source_name_and_required_packages(
    server: LanguageServer, tmp_path: Path, method: str, prefix: str
) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'meta module Tcl {meta command dispatch {args}}\n'
        'meta module Library {meta command app::dispatch {args}}\n'
    )
    source = tmp_path / 'main.tcl'
    text = prefix + 'namespace eval app {\n    proc dispatch {args} {}\n    dispatch\n}\n'
    source.write_text(text)
    open_server_document(server, text, uri=source.as_uri())

    shift = int(bool(prefix))
    response = server_position_request(
        server,
        method=f'textDocument/{method}',
        uri=source.as_uri(),
        line=2 + shift,
        character=5,
    )
    locations = cast(list[dict[str, Any]], response['result'])
    expected = [(source.as_uri(), 1 + shift)]
    if prefix:
        expected.append((config.as_uri(), 1))
    assert [(item['uri'], item['range']['start']['line']) for item in locations] == expected


@pytest.mark.parametrize('method', ['definition', 'declaration', 'implementation'])
def test_metadata_only_command_navigation_returns_each_active_declaration_once(
    server: LanguageServer, tmp_path: Path, method: str
) -> None:
    config = tmp_path / 'tcllsrc.tcl'
    config.write_text(
        'meta module Alpha {meta command dispatch {args}}\n'
        'meta module Beta {meta command dispatch {value}}\n'
        'module Alpha\n'
    )
    source = tmp_path / 'main.tcl'
    text = 'dispatch\n'
    source.write_text(text)
    open_server_document(server, text, uri=source.as_uri())

    response = server_position_request(
        server,
        method=f'textDocument/{method}',
        uri=source.as_uri(),
        line=0,
        character=1,
    )
    locations = cast(list[dict[str, Any]] | None, response['result']) or []
    expected = [] if method == 'implementation' else [(config.as_uri(), 0)]
    assert [(item['uri'], item['range']['start']['line']) for item in locations] == expected


@pytest.mark.parametrize('include_declaration', [False, True])
def test_metadata_navigation_does_not_add_metadata_to_source_references(
    server: LanguageServer, tmp_path: Path, include_declaration: bool
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('meta module Tcl {meta command dispatch {args}}\n')
    source = tmp_path / 'main.tcl'
    text = 'proc dispatch {args} {}\ndispatch\n'
    source.write_text(text)
    open_server_document(server, text, uri=source.as_uri())

    response = server_workspace_request(
        server,
        method='textDocument/references',
        params={
            'textDocument': {'uri': source.as_uri()},
            'position': {'line': 1, 'character': 1},
            'context': {'includeDeclaration': include_declaration},
        },
    )
    locations = cast(list[dict[str, Any]], response['result'])
    expected = [(source.as_uri(), 1)]
    if include_declaration:
        expected.insert(0, (source.as_uri(), 0))
    assert [(item['uri'], item['range']['start']['line']) for item in locations] == expected
