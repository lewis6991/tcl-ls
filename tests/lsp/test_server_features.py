from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from lsprotocol import types

from tcl_lsp.analysis import resolver as analysis_resolver
from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.analysis.model import CommandCall
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp import workspace_rebuild as lsp_workspace_rebuild
from tcl_lsp.parser import Parser, ParseResult
from tests.lsp.helpers import (
    MAIN_URI,
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
from tests.lsp_support import process_message
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
    (project_root / 'tcllsrc.tcl').write_text(
        'source .tcl-ls/sample.meta.tcl\nsource .tcl-ls/declaration.meta.tcl\n', encoding='utf-8'
    )

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


@pytest.mark.parametrize('include_declaration', [False, True])
def test_language_server_references_find_unopened_callers_of_an_implementation(
    server: LanguageServer,
    tmp_path: Path,
    include_declaration: bool,
) -> None:
    plugin_root = tmp_path / '.tcl-ls'
    write_sample_plugin_bundle(plugin_root)
    write_declaration_plugin_bundle(plugin_root)
    (tmp_path / 'tcllsrc.tcl').write_text(
        'source .tcl-ls/sample.meta.tcl\nsource .tcl-ls/declaration.meta.tcl\n', encoding='utf-8'
    )
    declaration = tmp_path / 'decl.tcl'
    declaration.write_text('dsl::declare ::app::init {}\n', encoding='utf-8')
    implementation = tmp_path / 'impl.tcl'
    implementation_text = (
        'source [file join [file dirname [info script]] decl.tcl]\ndsl::define ::app::init {} {}\n'
    )
    implementation.write_text(implementation_text, encoding='utf-8')
    caller = tmp_path / 'caller.tcl'
    caller.write_text(
        'source [file join [file dirname [info script]] decl.tcl]\nproc run {} {app::init}\n',
        encoding='utf-8',
    )
    (tmp_path / 'unrelated.tcl').write_text('app::init\n', encoding='utf-8')
    open_server_document(server, implementation_text, uri=implementation.as_uri())

    response = server_workspace_request(
        server,
        method='textDocument/references',
        params={
            'textDocument': {'uri': implementation.as_uri()},
            'position': {'line': 1, 'character': 20},
            'context': {'includeDeclaration': include_declaration},
        },
    )

    expected: list[dict[str, Any]] = [
        {
            'uri': caller.as_uri(),
            'range': {
                'start': {'line': 1, 'character': 13},
                'end': {'line': 1, 'character': 22},
            },
        },
    ]
    if include_declaration:
        expected.extend(
            {
                'uri': path.as_uri(),
                'range': {
                    'start': {'line': line, 'character': character},
                    'end': {'line': line, 'character': character + 11},
                },
            }
            for path, line, character in ((declaration, 0, 13), (implementation, 1, 12))
        )
    result = cast(list[dict[str, Any]], response['result'])
    assert sorted(result, key=lambda location: location['uri']) == sorted(
        expected, key=lambda location: location['uri']
    )


@pytest.mark.parametrize('root_kind', ['workspace-folder', 'root-uri', 'package-index'])
def test_language_server_references_use_current_text_within_the_workspace(
    server: LanguageServer, tmp_path: Path, root_kind: str
) -> None:
    project = tmp_path / 'project'
    library = project / 'lib'
    library.mkdir(parents=True)
    if root_kind == 'package-index':
        (project / 'pkgIndex.tcl').write_text('', encoding='utf-8')
    else:
        server.reset()
        root_params: dict[str, object] = (
            {'workspaceFolders': [{'uri': project.as_uri(), 'name': 'project'}]}
            if root_kind == 'workspace-folder'
            else {'rootUri': project.as_uri()}
        )
        process_message(
            server,
            {
                'jsonrpc': '2.0',
                'id': 0,
                'method': 'initialize',
                'params': {'capabilities': {}, **root_params},
            },
        )
    definition = library / 'defs.tcl'
    definition.write_text('proc old_name {} {}\n', encoding='utf-8')
    open_server_document(server, 'proc greet {} {}\ngreet\n', uri=definition.as_uri())
    caller = project / 'main.test'
    source = 'source [file join [file dirname [info script]] lib defs.tcl]\n'
    caller.write_text(source + 'greet\n', encoding='utf-8')
    (tmp_path / 'outside.tcl').write_text(f'source {{{definition}}}\ngreet\n', encoding='utf-8')
    documents = server.documents

    def references() -> set[tuple[str, int]]:
        response = server_workspace_request(
            server,
            method='textDocument/references',
            params={
                'textDocument': {'uri': definition.as_uri()},
                'position': {'line': 0, 'character': 6},
                'context': {'includeDeclaration': False},
            },
        )
        result = cast(list[dict[str, Any]], response['result'])
        return {(location['uri'], location['range']['start']['line']) for location in result}

    assert references() == {(definition.as_uri(), 1), (caller.as_uri(), 1)}
    assert server.documents is documents

    caller.write_text(source + '\ngreet\n', encoding='utf-8')
    assert references() == {(definition.as_uri(), 1), (caller.as_uri(), 2)}

    open_server_document(server, caller.read_text(encoding='utf-8'), uri=caller.as_uri())
    server.workspace.put_text_document(
        types.TextDocumentItem(
            uri=caller.as_uri(), language_id='tcl', version=2, text=source + 'puts changed\n'
        )
    )
    assert references() == {(definition.as_uri(), 1)}


def test_references_limit_resolution_and_refresh_when_the_selected_symbol_changes(
    server: LanguageServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('', encoding='utf-8')
    definition = tmp_path / 'defs.tcl'
    definitions = 'proc ::app::greet {} {}\nproc ::app::wave {} {}\n'
    definition.write_text(definitions, encoding='utf-8')
    caller = tmp_path / 'caller.tcl'
    callers = (
        'source [file join [file dirname [info script]] defs.tcl]\n'
        'namespace import ::app::*\n'
        'gr\\eet\n'
        '::app::greet\n'
        'rename greet salute\n'
        'salute\n'
        'rename salute hello\n'
        'hello\n'
        'wave\n'
        'puts unrelated\n'
        'set count 1\n'
        'puts $count\n'
    )
    caller.write_text(callers, encoding='utf-8')
    open_server_document(server, definitions, uri=definition.as_uri())

    calls: list[str | None] = []
    resolve = analysis_resolver.Resolver._resolve_command  # pyright: ignore[reportPrivateUsage]

    def record_resolution(
        self: analysis_resolver.Resolver,
        command: CommandCall,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if command.uri == caller.as_uri():
            calls.append(command.name)
        return resolve(self, command, *args, **kwargs)

    monkeypatch.setattr(analysis_resolver.Resolver, '_resolve_command', record_resolution)

    def references(uri: str, line: int, character: int) -> set[tuple[str, int]]:
        response = server_workspace_request(
            server,
            method='textDocument/references',
            params={
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': character},
                'context': {'includeDeclaration': True},
            },
        )
        result = cast(list[dict[str, Any]], response['result'])
        return {(location['uri'], location['range']['start']['line']) for location in result}

    greeting_references = references(definition.as_uri(), 0, 14)
    assert greeting_references == {
        (definition.as_uri(), 0),
        *((caller.as_uri(), line) for line in (2, 3, 4)),
    }
    assert set(calls) == {'greet', '::app::greet', 'salute'}

    calls.clear()
    assert references(definition.as_uri(), 0, 13) == greeting_references
    assert calls == []

    def unexpected_rebuild(*args: object, **kwargs: object) -> None:
        pytest.fail('Moving to another symbol must reuse the prepared workspace')

    calls.clear()
    with monkeypatch.context() as rebuild_patch:
        rebuild_patch.setattr(
            lsp_workspace_rebuild, 'prepare_workspace_documents', unexpected_rebuild
        )
        assert references(definition.as_uri(), 1, 14) == {
            (definition.as_uri(), 1),
            (caller.as_uri(), 8),
        }
    assert set(calls) == {'greet', 'salute', 'wave'}

    # A rename chain must retain its source bindings. A variable request must
    # use full resolution even after a command request populated the cache.
    open_server_document(server, callers, uri=caller.as_uri())
    assert references(caller.as_uri(), 7, 2) == {
        (caller.as_uri(), 6),
        (caller.as_uri(), 7),
    }
    assert references(caller.as_uri(), 10, 5) == {
        (caller.as_uri(), 10),
        (caller.as_uri(), 11),
    }


def test_references_reuse_unchanged_files_after_an_edit(
    server: LanguageServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text('', encoding='utf-8')
    definition = tmp_path / 'defs.tcl'
    text = 'proc greet {} {}\n'
    definition.write_text(text, encoding='utf-8')
    caller = tmp_path / 'caller.tcl'
    source = 'source [file join [file dirname [info script]] defs.tcl]\n'
    caller.write_text(source + 'greet\nregexp {(} text\n', encoding='utf-8')
    open_server_document(server, text, uri=definition.as_uri())
    assert server.semantic_tokens(definition.as_uri()) is not None

    parsed: list[str] = []
    parse_document = Parser.parse_document

    def record_parse(self: Parser, path: str, text: str) -> ParseResult:
        parsed.append(path)
        return parse_document(self, path=path, text=text)

    monkeypatch.setattr(Parser, 'parse_document', record_parse)

    def references(line: int = 0) -> set[tuple[str, int]]:
        response = server_workspace_request(
            server,
            method='textDocument/references',
            params={
                'textDocument': {'uri': definition.as_uri()},
                'position': {'line': line, 'character': 6},
                'context': {'includeDeclaration': False},
            },
        )
        result = cast(list[dict[str, Any]], response['result'])
        return {(location['uri'], location['range']['start']['line']) for location in result}

    def unexpected_diagnostics(*args: object, **kwargs: object) -> None:
        pytest.fail('Finding references must not run diagnostic checks')

    with monkeypatch.context() as diagnostics_patch:
        diagnostics_patch.setattr(analysis_resolver, 'collect_diagnostics', unexpected_diagnostics)
        assert references() == {(caller.as_uri(), 1)}
    assert definition.as_uri() not in parsed
    assert parsed.count(caller.as_uri()) == 1

    parsed.clear()
    assert references() == {(caller.as_uri(), 1)}
    assert parsed == []

    # Normal diagnostics must not evict the references cache. Reuse both the
    # updated open document and the unchanged caller on the next request.
    edited = '\n' + text
    server.workspace.put_text_document(
        types.TextDocumentItem(uri=definition.as_uri(), language_id='tcl', version=2, text=edited)
    )
    server.change_document(definition.as_uri(), edited, 2)
    assert server.semantic_tokens(definition.as_uri()) is not None
    parsed.clear()
    assert references(1) == {(caller.as_uri(), 1)}
    assert parsed == []

    caller.write_text(source + '\ngreet\n', encoding='utf-8')
    assert references(1) == {(caller.as_uri(), 2)}
    assert parsed == [caller.as_uri()]

    caller.unlink()
    assert references(1) == set()
    caller.with_suffix('.tm').write_text(source + 'greet\n', encoding='utf-8')
    assert references(1) == {(caller.with_suffix('.tm').as_uri(), 1)}


@pytest.mark.parametrize('changed_file', ['dependency', 'metadata'])
def test_references_refresh_cached_bodies_when_dependencies_or_metadata_change(
    server: LanguageServer, tmp_path: Path, changed_file: str
) -> None:
    metadata = tmp_path / 'commands.meta.tcl'
    metadata_text = 'meta module Sample {meta command sample::run {body} {enter tcl body 1}}\n'
    metadata.write_text(metadata_text, encoding='utf-8')
    (tmp_path / 'tcllsrc.tcl').write_text('source commands.meta.tcl\n', encoding='utf-8')
    definition = tmp_path / 'defs.tcl'
    definition.write_text('proc greet {} {}\n', encoding='utf-8')
    caller = tmp_path / 'caller.tcl'
    caller.write_text(
        'source [file join [file dirname [info script]] defs.tcl]\n'
        'source [file join [file dirname [info script]] deps.inc]\n'
        'sample::run {greet}\n',
        encoding='utf-8',
    )
    dependency = tmp_path / 'deps.inc'
    dependency_text = (
        'package require Sample\nsource [file join [file dirname [info script]] caller.tcl]\n'
    )
    dependency.write_text(dependency_text, encoding='utf-8')
    open_server_document(server, definition.read_text(encoding='utf-8'), uri=definition.as_uri())

    def references() -> list[dict[str, Any]]:
        response = server_workspace_request(
            server,
            method='textDocument/references',
            params={
                'textDocument': {'uri': definition.as_uri()},
                'position': {'line': 0, 'character': 6},
                'context': {'includeDeclaration': False},
            },
        )
        return cast(list[dict[str, Any]], response['result'])

    expected = references()
    assert len(expected) == 1
    assert expected[0]['uri'] == caller.as_uri()
    assert expected[0]['range']['start'] == {'line': 2, 'character': 13}

    for active in (False, True, False):
        if changed_file == 'dependency':
            dependency.write_text(
                dependency_text
                if active
                else dependency_text.replace('package require Sample\n', ''),
                encoding='utf-8',
            )
        else:
            metadata.write_text(
                metadata_text if active else metadata_text.replace('enter tcl body 1', ''),
                encoding='utf-8',
            )
        assert references() == (expected if active else [])


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
        ('meta module Tcl {\n    meta command set_local_mode {args}\n}\n'),
        encoding='utf-8',
    )
    (tmp_path / 'tcllsrc.tcl').write_text('source .tcl-ls/sample.meta.tcl\n', encoding='utf-8')

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
    assert 'Syntax: a subcommand followed by positional arguments and braced blocks.' in hover_value
    assert '**Declarations**' in hover_value
    for name in ('module', 'command', 'language', 'alias', 'override', 'source'):
        assert f'- `{name}`:' in hover_value
    assert 'meta command run {script}' in hover_value
    assert 'enter tcl body 1' in hover_value
    assert len(hover_value.splitlines()) < 40


@pytest.mark.parametrize(
    ('annotation', 'signature', 'syntax', 'example'),
    [
        (
            'enter tcl body 4',
            'enter language body selector',
            'positional arguments',
            'enter tcl body 4',
        ),
        ('bind 3 set', 'bind selector kind', 'positional arguments', 'bind 3 set'),
        ('ref 3', 'ref selector', 'positional arguments', 'ref 3'),
        ('option -start value', 'option name value', 'positional arguments', 'option -start value'),
        ('source 1 caller', 'source selector caller', 'positional arguments', 'source 1 caller'),
        (
            'package {literal TclOO}',
            'package {settings}',
            'key/value list',
            'package {literal TclOO}',
        ),
    ],
)
def test_metadata_annotation_hover_explains_its_syntax(
    server: LanguageServer, annotation: str, signature: str, syntax: str, example: str
) -> None:
    open_server_document(server, f'meta command wrapper {{a b c d}} {{\n    {annotation}\n}}\n')

    hover = hover_markdown_value(server, line=1, character=5)

    assert f'`{signature}`' in hover or f'\n{signature}\n' in hover
    assert f'Syntax: {syntax}.' in hover
    assert example in hover
    assert hover.count(f'Syntax: {syntax}.') == 1
    if syntax == 'positional arguments':
        assert f'{annotation.split()[0]} {{selector' not in hover
        assert 'enter {language' not in hover


@pytest.mark.parametrize(
    ('field', 'example'),
    [
        ('name {select 1}', 'name {select 1}'),
        (
            'params {select 2}',
            'params {select 2}',
        ),
        ('body {select 3}', 'body {select 3}'),
    ],
)
def test_metadata_procedure_field_hover_explains_grouped_settings(
    server: LanguageServer, field: str, example: str
) -> None:
    fields = ['name {select 1}', 'params {select 2}', 'body {select 3}']
    field_name = field.split()[0]
    field_index = next(i for i, value in enumerate(fields) if value.split()[0] == field_name)
    fields[field_index] = field
    field_text = '\n'.join(f'        {value}' for value in fields)
    open_server_document(
        server,
        'meta command declare {name header body} {\n'
        '    procedure {\n'
        f'{field_text}\n'
        '    }\n'
        '}\n',
    )

    hover = hover_markdown_value(server, line=2 + field_index, character=9)

    assert 'Syntax: key/value list.' in hover
    assert example in hover
    assert 'select' in hover
    assert hover.count('Syntax: key/value list.') == 1
    assert f'`{field_name} {{settings}}`' in hover or f'\n{field_name} {{settings}}\n' in hover
    assert f'{field_name} select selector' not in hover
    assert f'{field_name} literal value' not in hover
    assert f'{field_name} -' not in hover
    if field_name == 'params':
        assert '**Source (choose one)**' in hover
        assert '- `select selector`: read one runtime argument.' in hover
        assert '- `literal parameterList`: use a fixed Tcl parameter list.' in hover
        assert 'Use a Tcl plugin for other parameter syntaxes.' in hover
        assert '**Optional parser**' in hover
        assert '- `plugin {script procName}`:' in hover
        assert 'procName value info' in hover
        assert '`items {}` declares no parameters.' in hover
        assert '| Key |' not in hover


@pytest.mark.parametrize(
    ('text', 'token', 'signature', 'details'),
    [
        (
            'meta module Tcl {}',
            'module',
            'meta module name {body}',
            ('Included files inherit the module.', '`Tcl` and `TclOO` are active by default.'),
        ),
        (
            'meta source ../src/common.tcl',
            'source',
            'meta source path',
            ('Allowed only outside module blocks.', 'include metadata declarations instead.'),
        ),
        (
            'meta module Tcl {meta alias tcl_clock clock -module Tcl}',
            'alias',
            'meta alias name target -module moduleName',
            ('- `-module moduleName`:', 'Default: the enclosing module.'),
        ),
        (
            'meta module Tcl {meta override clock {args}}',
            'override',
            'meta override name {shape}',
            ('Requires a module block.', 'Default: `public`.'),
        ),
        (
            'meta command run {script} {enter tcl body 1}',
            'command',
            'meta command name {shape} {body}',
            ('**Forms**', '**Shape items**', '- `-visibility public|internal`:'),
        ),
        (
            'meta language tool-script {extends tcl; command prove {property}}',
            'language',
            'meta language name {body}',
            ('**Body commands**', 'Default: closed; only declared commands are valid.'),
        ),
        (
            'meta command tool {args} {command prove {property}}',
            'command prove',
            'command name {shape}',
            ('Describe a subcommand of the enclosing command.', 'Default: `public`.'),
        ),
        (
            'meta command run variants {form {script} {enter tcl body 1}}',
            'form',
            'form {shape} {body}',
            ('inside a `variants` block.', '`args` consumes the remaining arguments'),
        ),
        (
            'meta command declare {name params body} {procedure {name {select 1}; params {select 2}; body {select 3}}}',
            'procedure',
            'procedure {body}',
            ('**Fields**', '- `name`: required;', '- `params`: required;', 'Requires `body`.'),
        ),
        (
            'meta command declare {args} {plugin declare.tcl ::project::metadata::declare}',
            'plugin',
            'plugin script procName',
            ('**Arguments**', 'Plugin selectors count from 1 including the command name'),
        ),
        (
            'meta language tool-script {extends tcl}',
            'extends',
            'extends tcl',
            ('`tcl` is the only supported base language.', 'Default: closed;'),
        ),
        (
            'meta language tool-script {command prove {property}}',
            'command',
            'command name {shape}',
            ('Describe a command available in this embedded language.', '**Shape items**'),
        ),
        (
            'meta module Tcl {meta language tool-script {override prove {property}}}',
            'override',
            'override name {shape}',
            (
                'Replace a command from a lower module in this embedded language.',
                'Default: `public`.',
            ),
        ),
        (
            'meta command declare {name params body} {procedure {name {select 1}; params {select 2}; body {select 3}; language tcloo-method}}',
            'language',
            'language name',
            ('Requires a `body` field.', 'Default: `tcl`.'),
        ),
    ],
)
def test_metadata_declaration_hover_shows_syntax_options_and_example(
    server: LanguageServer, text: str, token: str, signature: str, details: tuple[str, ...]
) -> None:
    open_server_document(server, text + '\n')

    hover = hover_markdown_value(server, line=0, character=text.index(token) + 1)

    assert f'`{signature}`' in hover or f'\n{signature}\n' in hover
    assert hover.count('Syntax:') == 1
    assert '**Example**' in hover
    assert '```tcl' in hover
    for detail in details:
        assert detail in hover


@pytest.mark.parametrize(
    ('command', 'arguments', 'details'),
    [
        ('word', '3', 'The source ID is valid only in this plugin invocation.'),
        ('variable', 'common', 'Unknown, changed, or ambiguous values return an empty string.'),
        ('source_list_items', '$value', 'Invalid lists raise a Tcl error.'),
        ('slice', '$value 1 end', 'exclusive end index; `end` means the end of the string.'),
    ],
)
def test_plugin_source_query_hover_describes_its_contract(
    server: LanguageServer, command: str, arguments: str, details: str
) -> None:
    open_server_document(
        server,
        f'# tcl-ls: module TclLSPlugin\nset value {{}}\n::tcl_lsp::{command} {arguments}\n',
    )

    hover = hover_markdown_value(server, line=2, character=12)

    assert server.documents[MAIN_URI].analysis.diagnostics == ()
    assert details in hover
    assert '| Key |' not in hover
    assert 'read-only source item' in hover
    assert 'raw source content' in hover
    assert 'escapes stay literal' in hover.lower()
    assert 'editing fields does not change the source' in hover.lower()
