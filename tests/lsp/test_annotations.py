from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tcl_lsp.lsp import LanguageServer
from tests.lsp.helpers import (
    MAIN_URI,
    apply_semantic_token_edits,
    as_dict,
    change_server_document,
    completion_items,
    decode_semantic_tokens,
    hover_markdown_value,
    open_server_document,
    override_schedule_document_change,
    semantic_tokens_legend,
    server_document_request,
    server_semantic_token_delta_request,
    signature_help_result,
)


@pytest.mark.parametrize('comment_prefix', ['#', '##'])
def test_annotations_describe_a_sourced_procedure(
    server: LanguageServer, tmp_path: Path, comment_prefix: str
) -> None:
    definitions = """namespace eval properties {
    # @alias State "enabled" | "disabled"
    # @alias Snapshot dict<string, {state: State, names: string[]}>

    # Update selected properties.
    # @param actual Snapshot State before conversion.
    # @param bound integer|"" Conversion bound.
    #              An empty string means no bound.
    # @return [Snapshot, string[]] The updated table and changed names.
    proc update {actual {bound {}}} {return [list $actual {}]}
}
"""
    defs_path = tmp_path / 'defs.tcl'
    defs_path.write_text(definitions.replace('    #', f'    {comment_prefix}'), encoding='utf-8')
    uri = (tmp_path / 'main.tcl').as_uri()
    open_server_document(
        server,
        'source [file join [file dirname [info script]] defs.tcl]\nproperties::update {} \nproperties::up\n',
        uri=uri,
    )

    signature = (
        'proc ::properties::update(actual: Snapshot, bound: integer|"") -> [Snapshot, string[]]'
    )
    hover = hover_markdown_value(server, uri=uri, line=1, character=1)
    assert hover.startswith(f'```tcl\n{signature}\n```\n\nUpdate selected properties.')
    assert '`actual: Snapshot`: State before conversion.' in hover
    assert '`Snapshot = dict<string, {state: State, names: string[]}>`' in hover
    assert '`State = "enabled" | "disabled"`' in hover
    assert '@param' not in hover

    result = signature_help_result(server, uri=uri, line=1, character=len('properties::update {} '))
    assert result is not None
    info = as_dict(cast(list[object], result['signatures'])[0])
    assert info['label'] == signature
    assert result['activeParameter'] == 1
    parameters = [as_dict(item) for item in cast(list[object], info['parameters'])]
    assert parameters[1]['documentation'] == 'Conversion bound.\nAn empty string means no bound.'
    for parameter, expected in zip(
        parameters, ['actual: Snapshot', 'bound: integer|""'], strict=True
    ):
        start, end = cast(list[int], parameter['label'])
        assert signature[start:end] == expected
    documentation = as_dict(info['documentation'])
    assert documentation['kind'] == 'markdown'
    assert documentation['value'] == hover.split('```\n\n', 1)[1]

    items = completion_items(server, uri=uri, line=2, character=len('properties::up'))
    item = next(item for item in items if item['label'] == 'properties::update')
    assert item['detail'] == signature
    assert item['documentation'] == documentation
    alias_hover = hover_markdown_value(server, uri=defs_path.as_uri(), line=2, character=14)
    assert alias_hover == '`Snapshot = dict<string, {state: State, names: string[]}>`'


def test_annotations_apply_to_metadata_procedures(server: LanguageServer, tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        """meta module Tcl {
meta command define {name params body} {
    procedure {name select 1; params select 2; body select 3}
}
}
""",
        encoding='utf-8',
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    open_server_document(
        server,
        """# @param value string Input value.
# @return void
define accept {value} {puts $value}
accept hello
""",
        uri=uri,
    )
    assert hover_markdown_value(server, uri=uri, line=3, character=1).startswith(
        '```tcl\nproc ::accept(value: string) -> void\n```'
    )


def test_aliases_use_the_procedure_namespace_and_stop_at_cycles(server: LanguageServer) -> None:
    source = """# @alias Value string
namespace eval left {
    # @alias Value Next
    # @alias Next Value|integer
    # @param value Value
    proc use {value} {return $value}
}
namespace eval right {
    # @alias Value boolean
    # @param value ::Value
    proc use {value} {return $value}
}
left::use 1
right::use 2
"""
    open_server_document(server, source)
    left = hover_markdown_value(server, line=12, character=1)
    right = hover_markdown_value(server, line=13, character=1)
    assert left.count('`Value = Next`') == 1
    assert left.count('`Next = Value|integer`') == 1
    assert 'Value = string' not in left
    assert '`Value = string`' in right
    assert 'Next' not in right


def test_semantic_token_deltas_update_annotation_types(server: LanguageServer) -> None:
    source = '# @param value string\nproc use {value} {return $value}\n'
    open_server_document(server, source)
    initial = as_dict(
        server_document_request(server, method='textDocument/semanticTokens/full')['result']
    )

    def skip_document_change(uri: str, version: int) -> None:
        del uri, version

    original_schedule = server.schedule_document_change
    try:
        override_schedule_document_change(server, skip_document_change)
        change_server_document(server, source.replace('string', '"on"|"off"'))
        delta = as_dict(
            server_semantic_token_delta_request(
                server, previous_result_id=cast(str, initial['resultId'])
            )['result']
        )
    finally:
        override_schedule_document_change(server, original_schedule)
    updated = apply_semantic_token_edits(
        cast(list[int], initial['data']), cast(list[dict[str, object]], delta['edits'])
    )
    latest = as_dict(
        server_document_request(server, method='textDocument/semanticTokens/full')['result']
    )
    assert updated == latest['data']
    token_types, token_modifiers = semantic_tokens_legend(server)
    tokens = decode_semantic_tokens(
        updated, token_types=token_types, token_modifiers=token_modifiers
    )
    assert [
        token['type'] for token in tokens if token['line'] == 0 and token['type'] != 'comment'
    ] == ['keyword', 'parameter', 'string', 'operator', 'string']


def test_annotation_edits_refresh_signatures_and_cached_body_aliases(
    server: LanguageServer,
) -> None:
    source = """proc outer {} {
    # @alias Value string
    # @param value Value
    proc inner {value} {return $value}
    inner hello
}
"""
    open_server_document(server, source)
    assert '`Value = string`' in hover_markdown_value(server, line=4, character=5)
    server.change_document(MAIN_URI, '\n' + source, 2)
    assert '`Value = string`' in hover_markdown_value(server, line=5, character=5)
    server.change_document(MAIN_URI, '\n' + source.replace('Value string', 'Value integer'), 3)
    hover = hover_markdown_value(server, line=5, character=5)
    assert '`Value = integer`' in hover
    assert '`Value = string`' not in hover


@pytest.mark.parametrize(
    'annotation',
    [
        '@param value dict<string,',
        '@param value string|',
        '@param value',
        '@param value (string',
        '@param value string?',
        '@unknown value string',
    ],
)
def test_incomplete_or_unknown_annotations_remain_documentation(
    server: LanguageServer,
    annotation: str,
) -> None:
    open_server_document(server, f'# {annotation}\nproc use {{value}} {{return $value}}\nuse hi\n')
    assert hover_markdown_value(server, line=2, character=1) == (
        f'```tcl\nproc ::use(value)\n```\n\n{annotation}'
    )


def test_blank_lines_stop_annotations_attaching_to_a_procedure(server: LanguageServer) -> None:
    open_server_document(
        server, '# @param value integer\n\nproc use {value} {return $value}\nuse hi\n'
    )
    assert hover_markdown_value(server, line=3, character=1) == '```tcl\nproc ::use(value)\n```'


@pytest.mark.parametrize('comment_prefix', ['#', '##'])
def test_semantic_tokens_distinguish_annotation_parts_without_overlap(
    server: LanguageServer,
    comment_prefix: str,
) -> None:
    source = """namespace eval properties {
    # @alias Snapshot dict<string, {state: "on" | "off", count: 0|integer}>
    # @param actual Snapshot State before conversion.
    # @return [Snapshot, (string | integer)[]] Updated values.
    # @effects Reads tool state.
    proc update {actual} {return $actual}
    # @type Snapshot
    set current {}
    # @param incomplete dict<string,
    # Ordinary comments remain comments.
}
"""
    source = source.replace('    #', f'    {comment_prefix}')
    open_server_document(server, source)
    token_types, token_modifiers = semantic_tokens_legend(server)
    response = server_document_request(server, method='textDocument/semanticTokens/full')
    tokens = decode_semantic_tokens(
        cast(list[int], as_dict(response['result'])['data']),
        token_types=token_types,
        token_modifiers=token_modifiers,
    )
    lines = source.splitlines()
    parts: list[tuple[int, str, str, object]] = []
    previous_line, previous_end = -1, 0
    for token in tokens:
        line, start, length = (cast(int, token[key]) for key in ('line', 'character', 'length'))
        assert line > previous_line or start >= previous_end
        previous_line, previous_end = line, start + length
        parts.append(
            (
                line,
                lines[line][start : start + length],
                cast(str, token['type']),
                token['modifiers'],
            )
        )
    assert (1, '@alias', 'keyword', []) in parts
    assert (1, 'Snapshot', 'type', ['declaration']) in parts
    assert (1, 'dict', 'type', []) in parts
    assert (1, 'state', 'property', []) in parts
    assert (1, '"on"', 'string', []) in parts
    assert (1, '0', 'number', []) in parts
    assert (1, '|', 'operator', []) in parts
    assert (2, 'actual', 'parameter', []) in parts
    assert (2, 'Snapshot', 'type', []) in parts
    assert (2, ' State before conversion.', 'comment', []) in parts
    assert (3, '[]', 'operator', []) in parts
    assert (4, f'{comment_prefix} @effects Reads tool state.', 'comment', []) in parts
    assert (6, '@type', 'keyword', []) in parts
    assert (8, f'{comment_prefix} @param incomplete dict<string,', 'comment', []) in parts
    assert (9, f'{comment_prefix} Ordinary comments remain comments.', 'comment', []) in parts


def test_sourced_return_types_follow_imports_and_renames(
    server: LanguageServer,
    tmp_path: Path,
) -> None:
    provider = tmp_path / 'provider.tcl'
    provider.write_text("""namespace eval properties {
    # @alias State "enabled"|"disabled"
    # @return [State, integer]
    proc read_state {} {return {enabled 3}}
    namespace export read_state
}
""")
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """source [file join [file dirname [info script]] provider.tcl]
# @alias State "unrelated"
namespace import properties::read_state
rename read_state renamed_reader
rename lassign unpack
proc use {} {
    set pair [renamed_reader]
    unpack $pair state count
    puts $state
    puts $count
}
"""
    assert server.open_document(uri, text, 1) == ()
    refs = {ref.name: ref for ref in server.documents[uri].facts.variable_references}
    assert refs['pair'].type_info and refs['pair'].type_info.expression.text == '[State, integer]'
    assert refs['state'].type_info and refs['state'].type_info.expression.text == 'State'
    assert refs['state'].exact_values == ('enabled', 'disabled')
    assert refs['count'].type_info and refs['count'].type_info.expression.text == 'integer'
    hovers = [hover.contents for hover in server.documents[uri].analysis.hovers]
    assert 'lassign state: State' in hovers
    assert 'lassign count: integer' in hovers


def test_open_unrelated_file_does_not_supply_return_types(
    server: LanguageServer,
    tmp_path: Path,
) -> None:
    provider_uri = (tmp_path / 'provider.tcl').as_uri()
    caller_uri = (tmp_path / 'main.tcl').as_uri()
    server.open_document(provider_uri, '# @return integer\nproc read_state {} {return 1}\n', 1)
    server.open_document(caller_uri, 'proc use {} {set state [read_state]; puts $state}\n', 1)
    assert server.documents[caller_uri].facts.variable_references[0].type_info is None
