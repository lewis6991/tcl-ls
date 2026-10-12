from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from tcl_lsp.analysis import FactExtractor
from tcl_lsp.common import Position
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.parser import Parser, ParseResult
from tests.lsp.helpers import (
    MAIN_URI,
    apply_semantic_token_edits,
    as_dict,
    change_server_document,
    decode_semantic_tokens,
    fresh_server,
    open_server_document,
    override_schedule_document_change,
    semantic_token,
    semantic_tokens_legend,
    server_document_request,
    server_semantic_token_delta_request,
)
from tests.lsp_support import process_message


def test_language_server_initialize_advertises_semantic_tokens() -> None:
    server = fresh_server()
    response = as_dict(
        process_message(
            server,
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        )[0]
    )

    capabilities = as_dict(as_dict(response['result'])['capabilities'])
    semantic_tokens = as_dict(capabilities['semanticTokensProvider'])
    legend = as_dict(semantic_tokens['legend'])

    assert legend['tokenTypes'] == [
        'comment',
        'keyword',
        'namespace',
        'function',
        'parameter',
        'variable',
        'string',
        'operator',
    ]
    assert legend['tokenModifiers'] == ['declaration', 'defaultLibrary', 'deprecated']
    assert semantic_tokens['full'] == {'delta': True}
    assert capabilities['declarationProvider'] is True
    assert capabilities['implementationProvider'] is True
    document_link_provider = as_dict(capabilities['documentLinkProvider'])
    assert document_link_provider == {'resolveProvider': False}
    assert capabilities['foldingRangeProvider'] is True
    assert capabilities['renameProvider'] is True
    completion_provider = as_dict(capabilities['completionProvider'])
    assert completion_provider['triggerCharacters'] == ['$', ':', '-']
    signature_help_provider = as_dict(capabilities['signatureHelpProvider'])
    assert signature_help_provider['triggerCharacters'] == [' ', '\t']
    assert capabilities['documentHighlightProvider'] is True
    workspace_symbol_provider = as_dict(capabilities['workspaceSymbolProvider'])
    assert workspace_symbol_provider == {'resolveProvider': False}


def test_language_server_returns_semantic_tokens(server: LanguageServer) -> None:
    open_server_document(
        server,
        '# doc\n'
        'namespace eval app {\n'
        '    proc greet {name} {\n'
        '        set local $name\n'
        '        puts $local\n'
        '    }\n'
        '}\n'
        'app::greet World\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    expected_tokens = (
        semantic_token(line=0, character=0, length=5, token_type='comment'),
        semantic_token(line=1, character=0, length=9, token_type='keyword'),
        semantic_token(line=1, character=10, length=4, token_type='keyword'),
        semantic_token(
            line=1,
            character=15,
            length=3,
            token_type='namespace',
            modifiers=['declaration'],
        ),
        semantic_token(line=2, character=4, length=4, token_type='keyword'),
        semantic_token(
            line=2,
            character=9,
            length=5,
            token_type='function',
            modifiers=['declaration'],
        ),
        semantic_token(
            line=2,
            character=16,
            length=4,
            token_type='parameter',
            modifiers=['declaration'],
        ),
        semantic_token(line=3, character=8, length=3, token_type='keyword'),
        semantic_token(
            line=3,
            character=12,
            length=5,
            token_type='variable',
            modifiers=['declaration'],
        ),
        semantic_token(line=3, character=19, length=4, token_type='parameter'),
        semantic_token(
            line=4,
            character=8,
            length=4,
            token_type='function',
            modifiers=['defaultLibrary'],
        ),
        semantic_token(line=4, character=14, length=5, token_type='variable'),
        semantic_token(line=7, character=0, length=10, token_type='function'),
    )

    for expected_token in expected_tokens:
        assert expected_token in decoded


def test_language_server_returns_semantic_token_deltas(server: LanguageServer) -> None:
    initial_text = 'proc greet {} {\n    return ok\n}\n'
    changed_text = '\nproc greet {} {\n    return ok\n}\n'

    def skip_document_change(uri: str, version: int) -> None:
        del uri, version

    open_server_document(server, initial_text)

    initial_response = server_document_request(server, method='textDocument/semanticTokens/full')
    initial_result = as_dict(initial_response['result'])
    initial_data = cast(list[int], initial_result['data'])
    previous_result_id = cast(str, initial_result['resultId'])

    original_schedule_document_change = server.schedule_document_change
    try:
        override_schedule_document_change(server, skip_document_change)
        change_server_document(server, changed_text)

        delta_response = server_semantic_token_delta_request(
            server,
            previous_result_id=previous_result_id,
        )
    finally:
        override_schedule_document_change(server, original_schedule_document_change)

    delta_result = as_dict(delta_response['result'])
    edits = cast(list[dict[str, object]], delta_result['edits'])
    updated_data = apply_semantic_token_edits(initial_data, edits)

    latest_response = server_document_request(
        server,
        method='textDocument/semanticTokens/full',
        request_id=2,
    )
    latest_result = as_dict(latest_response['result'])
    latest_data = cast(list[int], latest_result['data'])

    assert updated_data == latest_data
    assert delta_result['resultId'] == latest_result['resultId']

    token_types, token_modifiers = semantic_tokens_legend(server)
    decoded = decode_semantic_tokens(
        updated_data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert semantic_token(line=1, character=0, length=4, token_type='keyword') in decoded
    assert (
        semantic_token(
            line=2,
            character=4,
            length=6,
            token_type='keyword',
        )
        in decoded
    )


def test_language_server_returns_full_semantic_tokens_when_delta_result_is_unknown(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'proc greet {} {\n    return ok\n}\n')

    delta_response = server_semantic_token_delta_request(
        server,
        previous_result_id='unknown-result',
    )
    delta_result = as_dict(delta_response['result'])

    full_response = server_document_request(
        server,
        method='textDocument/semanticTokens/full',
        request_id=2,
    )
    full_result = as_dict(full_response['result'])

    assert delta_result['data'] == full_result['data']
    assert delta_result['resultId'] == full_result['resultId']
    assert 'edits' not in delta_result


def test_language_server_returns_semantic_tokens_for_embedded_comments_and_if_keywords(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'proc greet {} {\n'
        '    if {1} then {\n'
        '        # then comment\n'
        '    } else {\n'
        '        # else comment\n'
        '    }\n'
        '}\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert {
        'line': 1,
        'character': 11,
        'length': 4,
        'type': 'keyword',
        'modifiers': [],
    } in decoded

    assert {
        'line': 3,
        'character': 6,
        'length': 4,
        'type': 'keyword',
        'modifiers': [],
    } in decoded

    assert {
        'line': 2,
        'character': 8,
        'length': 14,
        'type': 'comment',
        'modifiers': [],
    } in decoded

    assert {
        'line': 4,
        'character': 8,
        'length': 14,
        'type': 'comment',
        'modifiers': [],
    } in decoded


def test_language_server_returns_semantic_tokens_for_blocks_and_quoted_strings(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'proc greet {name} {\n    if {1} {\n        puts "hello [string trim $name]"\n    }\n}\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        semantic_token(line=0, character=18, length=1, token_type='operator'),
        semantic_token(line=1, character=11, length=1, token_type='operator'),
        semantic_token(line=2, character=13, length=1, token_type='string'),
        semantic_token(line=2, character=14, length=6, token_type='string'),
        semantic_token(line=2, character=20, length=1, token_type='operator'),
        semantic_token(line=2, character=38, length=1, token_type='operator'),
        semantic_token(line=2, character=39, length=1, token_type='string'),
        semantic_token(line=3, character=4, length=1, token_type='operator'),
        semantic_token(line=4, character=0, length=1, token_type='operator'),
    ):
        assert expected_token in decoded


def test_language_server_returns_semantic_tokens_for_return_keyword(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'proc greet {} {\n    return ok\n}\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert semantic_token(line=1, character=4, length=6, token_type='keyword') in decoded


def test_language_server_returns_semantic_tokens_for_semicolons(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'set first 1; set second 2\n')

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert semantic_token(line=0, character=11, length=1, token_type='operator') in decoded


def test_language_server_collects_lexical_spans_lazily_for_semantic_tokens(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'puts "hello"\n')

    document = server.current_managed_document(MAIN_URI)
    assert document is not None
    assert not document.lexical_spans_included

    server_document_request(server, method='textDocument/semanticTokens/full')

    document = server.current_managed_document(MAIN_URI)
    assert document is not None
    assert document.lexical_spans_included


def test_language_server_semantic_tokens_do_not_reextract_facts(
    server: LanguageServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract_count = 0
    original_extract = FactExtractor.extract

    def counting_extract(
        self: FactExtractor,
        parse_result: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal extract_count
        extract_count += 1
        return original_extract(self, cast(Any, parse_result), *args, **kwargs)

    monkeypatch.setattr(FactExtractor, 'extract', counting_extract)

    open_server_document(server, 'puts "hello"\n')
    initial_extract_count = extract_count
    assert initial_extract_count > 0

    server_document_request(server, method='textDocument/semanticTokens/full')

    assert extract_count == initial_extract_count


def test_highlighting_parses_nested_bodies_once(
    server: LanguageServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed_bodies: list[tuple[str, Position]] = []
    original_parse = Parser.parse_embedded_script

    def parse_body(
        self: Parser, source_id: str, text: str, start_position: Position
    ) -> ParseResult:
        if source_id == MAIN_URI:
            parsed_bodies.append((text, start_position))
        return original_parse(self, source_id, text, start_position)

    monkeypatch.setattr(Parser, 'parse_embedded_script', parse_body)
    open_server_document(
        server,
        'namespace eval app {\n'
        '    proc run {} {\n'
        '        if {1} {\n'
        '            # body\n'
        '            puts "hello"\n'
        '        }\n'
        '    }\n'
        '}\n',
    )
    result = server.semantic_tokens(MAIN_URI)
    assert result is not None
    assert len(parsed_bodies) == 3
    assert len(set(parsed_bodies)) == len(parsed_bodies)
    token_types, token_modifiers = semantic_tokens_legend(server)
    decoded = decode_semantic_tokens(
        list(result.data), token_types=token_types, token_modifiers=token_modifiers
    )
    assert semantic_token(line=3, character=12, length=6, token_type='comment') in decoded

    assert server.semantic_tokens(MAIN_URI) == result
    assert len(parsed_bodies) == 3


def test_language_server_returns_semantic_tokens_for_nested_delimiters_in_braced_words(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'proc init {{httpproxy {}}} {\n'
        '    if {! [info exists options]} {\n'
        '        switch -- $mode {\n'
        '            default { return [list {}] }\n'
        '        }\n'
        '    }\n'
        '}\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        semantic_token(line=0, character=22, length=1, token_type='operator'),
        semantic_token(line=0, character=23, length=1, token_type='operator'),
        semantic_token(line=1, character=10, length=1, token_type='operator'),
        semantic_token(line=1, character=30, length=1, token_type='operator'),
        semantic_token(line=3, character=20, length=1, token_type='operator'),
        semantic_token(line=3, character=29, length=1, token_type='operator'),
        semantic_token(line=3, character=35, length=1, token_type='operator'),
        semantic_token(line=3, character=36, length=1, token_type='operator'),
        semantic_token(line=3, character=37, length=1, token_type='operator'),
        semantic_token(line=3, character=39, length=1, token_type='operator'),
    ):
        assert expected_token in decoded


def test_language_server_returns_semantic_tokens_for_braced_variable_substitutions(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        'set value ${name}\nputs ${value}\n',
    )

    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    result = as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        semantic_token(line=0, character=11, length=1, token_type='operator'),
        semantic_token(line=0, character=16, length=1, token_type='operator'),
        semantic_token(line=1, character=6, length=1, token_type='operator'),
        semantic_token(line=1, character=12, length=1, token_type='operator'),
    ):
        assert expected_token in decoded


@pytest.mark.parametrize(
    ('initial_text', 'changed_text', 'expected_line'),
    [
        (
            'proc greet {} {\n    return ok\n}\n',
            '\nproc greet {} {\n    return ok\n}\n',
            1,
        ),
        (
            '\nproc greet {} {\n    return ok\n}\n',
            'proc greet {} {\n    return ok\n}\n',
            0,
        ),
    ],
)
def test_language_server_returns_semantic_tokens_for_latest_workspace_text_after_line_changes(
    server: LanguageServer,
    initial_text: str,
    changed_text: str,
    expected_line: int,
) -> None:
    def skip_document_change(uri: str, version: int) -> None:
        del uri, version

    open_server_document(server, initial_text)
    original_schedule_document_change = server.schedule_document_change
    try:
        override_schedule_document_change(server, skip_document_change)
        change_server_document(server, changed_text)

        token_types, token_modifiers = semantic_tokens_legend(server)
        response = server_document_request(server, method='textDocument/semanticTokens/full')
        result = as_dict(response['result'])
        data = cast(list[int], result['data'])

        decoded = decode_semantic_tokens(
            data,
            token_types=token_types,
            token_modifiers=token_modifiers,
        )

        assert (
            semantic_token(
                line=expected_line,
                character=0,
                length=4,
                token_type='keyword',
            )
            in decoded
        )
        assert (
            semantic_token(
                line=expected_line,
                character=5,
                length=5,
                token_type='function',
                modifiers=['declaration'],
            )
            in decoded
        )
    finally:
        override_schedule_document_change(server, original_schedule_document_change)


@pytest.mark.parametrize('visibility', ['public', 'internal'])
def test_semantic_visibility_follows_resolved_commands(
    tmp_path: Path, visibility: str, server: LanguageServer
) -> None:
    config = f"""meta module Tool {{
    meta command inspect -visibility {visibility} variants {{
        form {{}}
        form {{value}}
    }}
    meta alias inspect_alias inspect
    meta command ordinary {{}}
    meta command api {{subcommand args}} {{
        command inspect -visibility {visibility} {{}}
    }}
    meta command dsl {{body}} {{enter example body 1}}
    meta language example {{
        command inspect -visibility {visibility} {{}}
    }}
}}
"""
    (tmp_path / 'tcllsrc.tcl').write_text(config, encoding='utf-8')
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """# tcl-ls: module Tool
inspect
inspect value
inspect_alias
rename inspect renamed
renamed
ordinary
api inspect
dsl {inspect}
namespace eval local {
    proc inspect {} {}
    inspect
}
"""
    open_server_document(server, text, uri=uri)
    assert server.documents[uri].analysis.diagnostics == ()
    result = server.semantic_tokens(uri)
    assert result is not None
    token_types, token_modifiers = semantic_tokens_legend(server)
    decoded = decode_semantic_tokens(
        list(result.data), token_types=token_types, token_modifiers=token_modifiers
    )
    deprecated_positions = {
        (token['line'], token['character'])
        for token in decoded
        if 'deprecated' in cast(list[str], token['modifiers'])
    }
    assert deprecated_positions == (
        {(1, 0), (2, 0), (3, 0), (5, 0), (7, 4), (8, 5)} if visibility == 'internal' else set()
    )
    # The metadata DSL itself accepts visibility without spurious diagnostics.
    config_uri = (tmp_path / 'tcllsrc.tcl').as_uri()
    server.open_document(config_uri, config, 1)
    assert server.documents[config_uri].analysis.diagnostics == ()


def test_file_metadata_visibility_follows_the_procedure_definition(
    tmp_path: Path, server: LanguageServer
) -> None:
    (tmp_path / 'library.tcl').write_text('proc inspect {} {}\n', encoding='utf-8')
    (tmp_path / 'library.meta.tcl').write_text(
        'meta command inspect -visibility internal {}\n', encoding='utf-8'
    )
    (tmp_path / 'tcllsrc.tcl').write_text('source library.meta.tcl\n', encoding='utf-8')
    uri = (tmp_path / 'main.tcl').as_uri()
    open_server_document(
        server,
        'source [file join [file dirname [info script]] library.tcl]\n'
        'inspect\nnamespace eval local {proc inspect {} {}; inspect}\n',
        uri=uri,
    )

    assert server.documents[uri].analysis.diagnostics == ()
    result = server.semantic_tokens(uri)
    assert result is not None
    token_types, token_modifiers = semantic_tokens_legend(server)
    decoded = decode_semantic_tokens(
        list(result.data), token_types=token_types, token_modifiers=token_modifiers
    )
    assert [token for token in decoded if 'deprecated' in cast(list[str], token['modifiers'])] == [
        semantic_token(
            line=1, character=0, length=7, token_type='function', modifiers=['deprecated']
        )
    ]


def test_visibility_obeys_module_scope(tmp_path: Path, server: LanguageServer) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command inspect {}}\n'
        'meta module Tool {meta override inspect -visibility internal {}}\n',
        encoding='utf-8',
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    open_server_document(
        server,
        'inspect\nif {1} {\n# tcl-ls: module Tool\ninspect\n}\ninspect\n',
        uri=uri,
    )

    assert server.documents[uri].analysis.diagnostics == ()
    result = server.semantic_tokens(uri)
    assert result is not None
    token_types, token_modifiers = semantic_tokens_legend(server)
    decoded = decode_semantic_tokens(
        list(result.data), token_types=token_types, token_modifiers=token_modifiers
    )
    assert [token for token in decoded if 'deprecated' in cast(list[str], token['modifiers'])] == [
        semantic_token(
            line=3,
            character=0,
            length=7,
            token_type='function',
            modifiers=['defaultLibrary', 'deprecated'],
        )
    ]
