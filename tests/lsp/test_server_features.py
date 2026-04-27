from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from lsprotocol import types

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp import workspace_rebuild as lsp_workspace_rebuild
from tests.lsp.helpers import (
    as_dict,
    change_server_document,
    completion_items,
    hover_markdown_value,
    open_server_document,
    override_schedule_document_change,
    server_document_request,
    server_position_request,
    server_workspace_request,
    signature_help_result,
)
from tests.project_support import (
    write_declaration_plugin_bundle,
    write_sample_library_root,
    write_sample_plugin_bundle,
)


def test_language_server_hover_uses_markdown_code_fences_for_signatures(
    server: LanguageServer,
) -> None:
    open_server_document(
        server,
        '# Greets a user by name.\nproc greet {name} {puts $name}\ngreet World\n',
    )

    hover_value = hover_markdown_value(server, line=2, character=1)
    assert hover_value == '```tcl\nproc ::greet(name)\n```\n\nGreets a user by name.'


def test_language_server_returns_command_completion_items(server: LanguageServer) -> None:
    open_server_document(server, 'proc greet {} {return ok}\ngr\n')

    items = completion_items(server, line=1, character=2)
    greet_item = next(item for item in items if item['label'] == 'greet')

    assert greet_item['detail'] == 'proc ::greet()'


def test_language_server_prepares_function_rename_for_qualified_names(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'proc ::app::greet {} {return ok}\n::app::greet\n')

    response = server_position_request(
        server,
        method='textDocument/prepareRename',
        line=1,
        character=8,
    )

    assert response['result'] == {
        'range': {
            'start': {'line': 1, 'character': 7},
            'end': {'line': 1, 'character': 12},
        },
        'placeholder': 'greet',
    }


def test_language_server_prepares_variable_rename_for_qualified_variables(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'set ::app::result 1\nputs $::app::result\n')

    response = server_position_request(
        server,
        method='textDocument/prepareRename',
        line=1,
        character=15,
    )

    assert response['result'] == {
        'range': {
            'start': {'line': 1, 'character': 13},
            'end': {'line': 1, 'character': 19},
        },
        'placeholder': 'result',
    }


def test_language_server_returns_declaration_and_implementation_locations(
    server: LanguageServer,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    plugin_root = project_root / '.tcl-ls'
    write_sample_plugin_bundle(plugin_root)
    write_declaration_plugin_bundle(plugin_root)
    project_root.mkdir(exist_ok=True)
    (project_root / 'tcllsrc.tcl').write_text('plugin-path .tcl-ls\n', encoding='utf-8')

    declaration_path = project_root / 'decl.tcl'
    declaration_path.write_text('dsl::declare greet {{name}}\n', encoding='utf-8')
    implementation_path = project_root / 'impl.tcl'
    implementation_path.write_text(
        'dsl::define greet {{name}} {puts $name}\n',
        encoding='utf-8',
    )
    main_path = project_root / 'main.tcl'
    source_text = (
        'source [file join [file dirname [info script]] decl.tcl]\n'
        'source [file join [file dirname [info script]] impl.tcl]\n'
        'greet World\n'
    )
    main_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=main_path.as_uri())

    declaration_response = server_position_request(
        server,
        method='textDocument/declaration',
        uri=main_path.as_uri(),
        line=2,
        character=1,
    )
    declaration_result = cast(list[dict[str, object]], declaration_response['result'])
    assert {location['uri'] for location in declaration_result} == {
        declaration_path.as_uri(),
        implementation_path.as_uri(),
    }

    implementation_response = server_position_request(
        server,
        method='textDocument/implementation',
        uri=main_path.as_uri(),
        line=2,
        character=1,
    )
    implementation_result = cast(list[dict[str, object]], implementation_response['result'])
    assert implementation_result == [
        {
            'uri': implementation_path.as_uri(),
            'range': {
                'start': {'line': 0, 'character': 12},
                'end': {'line': 0, 'character': 17},
            },
        }
    ]


def test_language_server_returns_folding_ranges(server: LanguageServer) -> None:
    open_server_document(
        server,
        'namespace eval app {\n    proc greet {name} {\n        puts $name\n    }\n}\n',
    )

    response = server_document_request(server, method='textDocument/foldingRange')
    result = cast(list[dict[str, object]], response['result'])

    assert {(item['startLine'], item['endLine']) for item in result} == {(0, 4), (1, 3)}


def test_language_server_returns_document_links_for_sources_and_packages(
    server: LanguageServer,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text('proc greet {} {return ok}\n', encoding='utf-8')

    library_root = tmp_path / 'tcllib'
    package_root = write_sample_library_root(library_root)
    package_source_path = package_root / 'samplelib.tcl'

    (project_root / 'tcllsrc.tcl').write_text('lib-path ../tcllib\n', encoding='utf-8')
    main_path = project_root / 'main.tcl'
    source_text = (
        'source [file join [file dirname [info script]] helper.inc]\npackage require samplelib\n'
    )
    main_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=main_path.as_uri())

    response = server_document_request(
        server,
        method='textDocument/documentLink',
        uri=main_path.as_uri(),
    )
    result = cast(list[dict[str, object]], response['result'])

    assert {link['target'] for link in result} == {
        helper_path.as_uri(),
        package_source_path.as_uri(),
    }


def test_language_server_returns_absolute_plugin_metadata_completion_items(
    server: LanguageServer,
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / '.tcl-ls'
    plugin_root.mkdir()
    (plugin_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\nmeta command set_local_mode {args}\n',
        encoding='utf-8',
    )
    (tmp_path / 'tcllsrc.tcl').write_text('plugin-path .tcl-ls\n', encoding='utf-8')

    source_path = tmp_path / 'main.tcl'
    source_text = '::set_lo\n'
    source_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=source_path.as_uri())

    items = completion_items(
        server,
        uri=source_path.as_uri(),
        line=0,
        character=len('::set_lo'),
    )
    item = next(item for item in items if item['label'] == '::set_local_mode')

    assert item['detail'] == 'Tcl: set_local_mode {args}'


def test_language_server_marks_large_command_completion_lists_incomplete(
    server: LanguageServer,
) -> None:
    source_text = ''.join(f'proc p{index} {{}} {{}}\n' for index in range(500)) + 'p\n'
    open_server_document(server, source_text)

    completion_response = server_position_request(
        server,
        method='textDocument/completion',
        line=500,
        character=1,
    )
    result = as_dict(completion_response['result'])
    items = cast(list[dict[str, object]], result['items'])

    assert result['isIncomplete'] is True
    assert len(items) == 200
    assert items[0]['label'] == 'p0'


def test_language_server_completion_uses_live_text_before_reanalysis(
    server: LanguageServer,
) -> None:
    initial_text = 'namespace eval ::fts { proc hello {} {} }\n\n'
    changed_text = 'namespace eval ::fts { proc hello {} {} }\nfts::\n'

    def skip_document_change(uri: str, version: int) -> None:
        del uri, version

    open_server_document(server, initial_text)

    original_schedule_document_change = server.schedule_document_change
    try:
        override_schedule_document_change(server, skip_document_change)
        change_server_document(server, changed_text)
        items = completion_items(server, line=1, character=len('fts::'))
    finally:
        override_schedule_document_change(server, original_schedule_document_change)

    assert any(item['label'] == 'fts::hello' for item in items)


def test_language_server_returns_builtin_subcommand_completion_items(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'binary de\n')

    items = completion_items(server, line=0, character=len('binary de'))
    decode_item = next(item for item in items if item['label'] == 'decode')

    assert decode_item['detail'] == 'Tcl: binary decode {format ?-option value ...? data}'


def test_language_server_returns_builtin_subcommand_completion_items_mid_word(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'binary decode foo\n')

    items = completion_items(server, line=0, character=len('binary de'))
    decode_item = next(item for item in items if item['label'] == 'decode')

    assert decode_item['detail'] == 'Tcl: binary decode {format ?-option value ...? data}'


def test_language_server_returns_builtin_option_completion_items(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'regexp -\n')

    items = completion_items(server, line=0, character=len('regexp -'))
    nocase_item = next(item for item in items if item['label'] == '-nocase')

    assert nocase_item['detail'] == 'option for regexp'


def test_language_server_returns_variable_completion_items(server: LanguageServer) -> None:
    source_text = 'proc run {value} {\n    set local $value\n    puts $\n}\n'
    open_server_document(server, source_text)

    line = source_text.splitlines()[2]
    items = completion_items(
        server,
        line=2,
        character=line.index('$') + 1,
    )

    item_by_label = {cast(str, item['label']): item for item in items}
    assert item_by_label['local']['detail'] == 'set local'
    assert item_by_label['value']['detail'] == 'parameter value'


def test_language_server_returns_variable_completion_items_mid_word(
    server: LanguageServer,
) -> None:
    source_text = 'proc run {value} {\n    puts $value\n}\n'
    open_server_document(server, source_text)

    items = completion_items(
        server,
        line=1,
        character=len('    puts $va'),
    )

    value_item = next(item for item in items if item['label'] == 'value')
    assert value_item['detail'] == 'parameter value'


def test_language_server_returns_package_completion_items(
    server: LanguageServer, tmp_path: Path
) -> None:
    project_root = tmp_path / 'workspace'
    write_sample_library_root(tmp_path / 'tcllib')
    project_root.mkdir()
    (project_root / 'tcllsrc.tcl').write_text('lib-path ../tcllib\n', encoding='utf-8')

    source_path = project_root / 'main.tcl'
    source_text = 'package require sa\n'
    source_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=source_path.as_uri())

    items = completion_items(
        server,
        uri=source_path.as_uri(),
        line=0,
        character=len('package require sa'),
    )
    samplelib_item = next(item for item in items if item['label'] == 'samplelib')

    assert samplelib_item['detail'] == 'workspace package'


def test_language_server_returns_package_completion_items_without_loading_package_indexes(
    server: LanguageServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules_root = tmp_path / 'tcllib' / 'modules'
    grammar_fa_dir = modules_root / 'grammar_fa'
    unused_dir = modules_root / 'unused_dir'
    grammar_fa_dir.mkdir(parents=True)
    unused_dir.mkdir()

    grammar_pkg_index = grammar_fa_dir / 'pkgIndex.tcl'
    grammar_pkg_index.write_text(
        'package ifneeded grammar::fa 1.0 [list source [file join $dir fa.tcl]]\n',
        encoding='utf-8',
    )
    (grammar_fa_dir / 'fa.tcl').write_text(
        'package provide grammar::fa 1.0\nproc grammar::fa::run {} {return ok}\n',
        encoding='utf-8',
    )
    unused_pkg_index = unused_dir / 'pkgIndex.tcl'
    unused_pkg_index.write_text(
        'package ifneeded unused::pkg 1.0 [list source [file join $dir unused.tcl]]\n',
        encoding='utf-8',
    )
    (unused_dir / 'unused.tcl').write_text(
        'package provide unused::pkg 1.0\nproc unused::pkg::run {} {return ok}\n',
        encoding='utf-8',
    )

    loaded_pkg_indexes: list[Path] = []
    original_load_package_index = lsp_workspace_rebuild.load_package_index

    def counting_load_package_index(
        path: Path,
        *,
        parser: object | None = None,
    ) -> object:
        loaded_pkg_indexes.append(path.resolve(strict=False))
        return original_load_package_index(path, parser=cast(Any, parser))

    monkeypatch.setattr(lsp_workspace_rebuild, 'load_package_index', counting_load_package_index)

    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'tcllsrc.tcl').write_text('lib-path ../tcllib/modules\n', encoding='utf-8')

    source_path = project_root / 'main.tcl'
    source_text = 'package require gra\n'
    source_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=source_path.as_uri())

    items = completion_items(
        server,
        uri=source_path.as_uri(),
        line=0,
        character=len('package require gra'),
    )
    grammar_item = next(item for item in items if item['label'] == 'grammar::fa')

    assert grammar_item['detail'] == 'workspace package'
    assert loaded_pkg_indexes == []
    assert grammar_pkg_index.resolve(strict=False) not in loaded_pkg_indexes
    assert unused_pkg_index.resolve(strict=False) not in loaded_pkg_indexes


def test_language_server_returns_proc_signature_help(server: LanguageServer) -> None:
    open_server_document(server, 'proc greet {name times} {return ok}\ngreet \n')

    result = signature_help_result(server, line=1, character=len('greet '))

    assert result is not None
    signatures = cast(list[dict[str, object]], result['signatures'])
    assert signatures[0]['label'] == 'proc ::greet(name, times)'
    assert result['activeSignature'] == 0
    assert result['activeParameter'] == 0


def test_language_server_returns_proc_signature_help_before_later_arguments(
    server: LanguageServer,
) -> None:
    open_server_document(server, 'proc greet {name times} {return ok}\ngreet name times\n')

    result = signature_help_result(server, line=1, character=len('greet '))

    assert result is not None
    signatures = cast(list[dict[str, object]], result['signatures'])
    assert signatures[0]['label'] == 'proc ::greet(name, times)'
    assert result['activeSignature'] == 0
    assert result['activeParameter'] == 0


def test_language_server_returns_builtin_signature_help(server: LanguageServer) -> None:
    open_server_document(server, 'set \n')

    result = signature_help_result(server, line=0, character=len('set '))

    assert result is not None
    signatures = cast(list[dict[str, object]], result['signatures'])
    assert signatures[0]['label'] == 'set {varName ? newValue ?}'
    assert result['activeParameter'] is None


def test_language_server_returns_document_highlights(server: LanguageServer) -> None:
    source_text = 'proc run {value} {\n    set local $value\n    puts $local\n}\n'
    open_server_document(server, source_text)

    line = source_text.splitlines()[2]
    response = server_position_request(
        server,
        method='textDocument/documentHighlight',
        line=2,
        character=line.index('$local') + 1,
    )
    result = cast(list[dict[str, object]], response['result'])

    assert result == [
        {
            'range': {
                'start': {'line': 1, 'character': 8},
                'end': {'line': 1, 'character': 13},
            },
            'kind': types.DocumentHighlightKind.Write,
        },
        {
            'range': {
                'start': {'line': 2, 'character': 9},
                'end': {'line': 2, 'character': 15},
            },
            'kind': types.DocumentHighlightKind.Read,
        },
    ]


def test_language_server_returns_workspace_symbols(server: LanguageServer, tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text('proc greet {} {return ok}\n', encoding='utf-8')

    main_path = project_root / 'main.tcl'
    source_text = 'source [file join [file dirname [info script]] helper.inc]\n'
    main_path.write_text(source_text, encoding='utf-8')

    open_server_document(server, source_text, uri=main_path.as_uri())

    response = server_workspace_request(
        server,
        method='workspace/symbol',
        params={'query': 'greet'},
    )
    result = cast(list[dict[str, object]], response['result'])

    greet_symbol = next(symbol for symbol in result if symbol['name'] == '::greet')
    location = as_dict(greet_symbol['location'])
    assert location['uri'] == helper_path.as_uri()


@pytest.mark.parametrize(
    ('text', 'expected_prefix', 'expected_fragments'),
    [
        (
            'pwd\n',
            '```tcl\npwd\n```\n\nReturn the absolute path of the current working directory.',
            ('Returns the absolute path name of the current working directory.',),
        ),
        (
            'set value 1\n',
            '```tcl\nset {varName ? newValue ?}\n```\n\nRead and write variables.',
            ('With one argument, return the current value of varName.',),
        ),
        (
            'after 100\n',
            '```tcl\nafter\n```\n\n',
            (
                '`after {ms}`\nExecute a command after a time delay',
                '`after {info {id {}}}`\nReturn information about scheduled after handlers',
            ),
        ),
    ],
)
def test_language_server_hover_formats_builtin_commands(
    server: LanguageServer,
    text: str,
    expected_prefix: str,
    expected_fragments: tuple[str, ...],
) -> None:
    open_server_document(server, text)

    hover_value = hover_markdown_value(server, line=0, character=1)
    assert hover_value.startswith(expected_prefix)
    for fragment in expected_fragments:
        assert fragment in hover_value


def test_language_server_hover_formats_dynamic_binding_sets_as_code_block(
    server: LanguageServer,
) -> None:
    source_text = (
        'proc run {strategy} {\n'
        '    foreach v {mode run_limit engines} {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '}\n'
    )
    open_server_document(server, source_text)

    hover_value = hover_markdown_value(
        server,
        line=2,
        character=source_text.splitlines()[2].index('$v') + 1,
    )
    assert hover_value == '```tcl\nset mode\nset run_limit\nset engines\n```'


@pytest.mark.parametrize(
    ('text', 'character', 'builtin_name'),
    [
        ('namespace current\n', 11, 'namespace current'),
        ('namespace eval app {}\n', 11, 'namespace eval'),
        ('namespace code {puts hi}\n', 11, 'namespace code'),
        ('namespace ensemble create\n', 20, 'namespace ensemble create'),
        ('dict get {a 1} a\n', 6, 'dict get'),
        ('trace add command foo delete cb\n', 12, 'trace add command'),
        ('binary encode base64 data\n', 15, 'binary encode base64'),
    ],
)
def test_language_server_hover_formats_builtin_subcommands(
    server: LanguageServer,
    text: str,
    character: int,
    builtin_name: str,
) -> None:
    open_server_document(server, text)

    builtin = builtin_command(builtin_name)
    assert builtin is not None
    assert len(builtin.overloads) == 1
    overload = builtin.overloads[0]
    heading = overload.signature.removesuffix(' {}')

    hover_value = hover_markdown_value(server, line=0, character=character)
    assert hover_value == f'```tcl\n{heading}\n```\n\n{overload.documentation}'


def test_language_server_hover_formats_meta_builtin_command(server: LanguageServer) -> None:
    open_server_document(server, 'meta command after {ms}\n')

    hover_value = hover_markdown_value(server, line=0, character=1)
    assert hover_value.startswith('```tcl\nmeta {subcommand args}\n```\n\n')
    assert 'Top-level declarations:' in hover_value
    assert 'meta language languageName {' in hover_value
    assert '`extends tcl` is an optional ordinary clause inside a `meta language` body.' in (
        hover_value
    )
    assert 'plugin script procName' in hover_value
    assert 'structured documentation instead of executable behavior' in hover_value.replace(
        '\n', ' '
    )
    assert 'option name value' in hover_value
