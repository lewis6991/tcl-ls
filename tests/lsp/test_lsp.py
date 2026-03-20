from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from lsprotocol import types
from pygls.protocol.json_rpc import RPCMessage
from tests.lsp_service import LanguageService
from tests.lsp_support import process_message

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.lsp import LanguageServer
from tcl_lsp.lsp import server as lsp_server

_MAIN_URI = 'file:///main.tcl'


class _NonClosingBytesIO(BytesIO):
    def close(self) -> None:
        self.flush()


class _CaptureWriter:
    def __init__(self, stream: BytesIO) -> None:
        self._stream = stream

    def close(self) -> None:
        self._stream.flush()

    def write(self, data: bytes) -> None:
        self._stream.write(data)
        self._stream.flush()


def _fresh_server() -> LanguageServer:
    lsp_server.reset()
    return lsp_server


def _override_open_document(server: LanguageServer, open_document: object) -> None:
    cast(Any, server).open_document = open_document


def _override_change_document(server: LanguageServer, change_document: object) -> None:
    cast(Any, server)._change_document = change_document


def _override_schedule_document_change(
    server: LanguageServer,
    schedule_document_change: object,
) -> None:
    cast(Any, server).schedule_document_change = schedule_document_change


def _open_server_document(
    server: LanguageServer,
    text: str,
    *,
    uri: str = _MAIN_URI,
    version: int = 1,
) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': uri,
                    'languageId': 'tcl',
                    'version': version,
                    'text': text,
                }
            },
        },
    )


def _change_server_document(
    server: LanguageServer,
    text: str,
    *,
    uri: str = _MAIN_URI,
    version: int = 2,
) -> None:
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {
                    'uri': uri,
                    'version': version,
                },
                'contentChanges': [{'text': text}],
            },
        },
    )


def _write_sample_library_root(library_root: Path) -> Path:
    package_root = library_root / 'modules' / 'samplelib'
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded samplelib 1.0 [list source [file join $dir samplelib.tcl]]\n',
        encoding='utf-8',
    )
    (package_root / 'samplelib.tcl').write_text(
        'package provide samplelib 1.0\nproc samplelib::greet {} {return ok}\n',
        encoding='utf-8',
    )
    return package_root


def _write_transitive_package_workspace(workspace_root: Path) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (workspace_root / 'helper.tcl').write_text(
        'package require json\npackage provide helper 1.0\n',
        encoding='utf-8',
    )
    source_path = workspace_root / 'main.tcl'
    source_text = 'package require helper\njson::json2dict {}\n'
    source_path.write_text(source_text, encoding='utf-8')
    return source_path


def _server_position_request(
    server: LanguageServer,
    *,
    method: str,
    line: int,
    character: int,
    uri: str = _MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': character},
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return _as_dict(response)


def _server_document_request(
    server: LanguageServer,
    *,
    method: str,
    uri: str = _MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': {
                'textDocument': {'uri': uri},
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return _as_dict(response)


def _server_semantic_token_delta_request(
    server: LanguageServer,
    *,
    previous_result_id: str,
    uri: str = _MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': 'textDocument/semanticTokens/full/delta',
            'params': {
                'textDocument': {'uri': uri},
                'previousResultId': previous_result_id,
            },
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return _as_dict(response)


def _server_workspace_request(
    server: LanguageServer,
    *,
    method: str,
    params: dict[str, object],
    request_id: int = 1,
) -> dict[str, object]:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': params,
        },
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return _as_dict(response)


def _semantic_tokens_legend(server: LanguageServer) -> tuple[list[str], list[str]]:
    semantic_tokens_provider = server.server_capabilities.semantic_tokens_provider
    assert semantic_tokens_provider is not None
    legend = semantic_tokens_provider.legend
    token_types = cast(list[str], legend.token_types)
    token_modifiers = cast(list[str], legend.token_modifiers)
    return token_types, token_modifiers


def _decode_semantic_tokens(
    data: list[int],
    *,
    token_types: list[str],
    token_modifiers: list[str],
) -> list[dict[str, object]]:
    line = 0
    character = 0
    decoded: list[dict[str, object]] = []
    for index in range(0, len(data), 5):
        delta_line, delta_character, length, token_type_index, modifier_bits = data[
            index : index + 5
        ]
        line += delta_line
        if delta_line:
            character = delta_character
        else:
            character += delta_character
        decoded.append(
            {
                'line': line,
                'character': character,
                'length': length,
                'type': token_types[token_type_index],
                'modifiers': [
                    modifier
                    for bit_index, modifier in enumerate(token_modifiers)
                    if modifier_bits & (1 << bit_index)
                ],
            }
        )
    return decoded


def _apply_semantic_token_edits(
    data: list[int],
    edits: list[dict[str, object]],
) -> list[int]:
    updated = list(data)
    for edit in edits:
        replacement = edit.get('data')
        updated[
            cast(int, edit['start']) : cast(int, edit['start']) + cast(int, edit['deleteCount'])
        ] = [] if replacement is None else cast(list[int], replacement)
    return updated


def _semantic_token(
    *,
    line: int,
    character: int,
    length: int,
    token_type: str,
    modifiers: list[str] | None = None,
) -> dict[str, object]:
    return {
        'line': line,
        'character': character,
        'length': length,
        'type': token_type,
        'modifiers': [] if modifiers is None else modifiers,
    }


def _hover_markdown_value(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = _MAIN_URI,
) -> str:
    hover_response = _server_position_request(
        server,
        method='textDocument/hover',
        uri=uri,
        line=line,
        character=character,
    )
    hover_result = _as_dict(hover_response['result'])
    hover_contents = _as_dict(hover_result['contents'])
    assert hover_contents['kind'] == 'markdown'
    return cast(str, hover_contents['value'])


def _completion_items(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = _MAIN_URI,
) -> list[dict[str, object]]:
    completion_response = _server_position_request(
        server,
        method='textDocument/completion',
        uri=uri,
        line=line,
        character=character,
    )
    result = completion_response['result']
    if isinstance(result, list):
        return cast(list[dict[str, object]], result)
    completion_list = _as_dict(result)
    return cast(list[dict[str, object]], completion_list['items'])


def _signature_help_result(
    server: LanguageServer,
    *,
    line: int,
    character: int,
    uri: str = _MAIN_URI,
) -> dict[str, object] | None:
    signature_response = _server_position_request(
        server,
        method='textDocument/signatureHelp',
        uri=uri,
        line=line,
        character=character,
    )
    result = signature_response['result']
    if result is None:
        return None
    return _as_dict(result)


def _write_sample_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'sample.tcl'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::procedure {words info} {\n'
        '    if {[llength $words] < 4} {\n'
        '        return {}\n'
        '    }\n'
        '    return [list [list procedure [dict create \\\n'
        '        name-index 1 \\\n'
        '        params-word-index 2 \\\n'
        '        params [::tcl_lsp::plugins::sample::parameterNames [lindex $words 2]] \\\n'
        '        body-index 3 \\\n'
        '    ]]]\n'
        '}\n'
        'proc ::tcl_lsp::plugins::sample::parameterNames {parameter_list} {\n'
        '    set names {}\n'
        '    if {[catch {\n'
        '        foreach arg_def $parameter_list {\n'
        '            set name [lindex $arg_def 0]\n'
        '            if {$name eq ""} {\n'
        '                continue\n'
        '            }\n'
        '            lappend names $name\n'
        '        }\n'
        '    }]} {\n'
        '        return {}\n'
        '    }\n'
        '    return $names\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'sample.meta.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        '# Define a procedure using a project-local wrapper command.\n'
        'meta command dsl::define {name params body} {\n'
        '    plugin sample.tcl ::tcl_lsp::plugins::sample::procedure\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path


def test_language_service_does_not_resolve_unrelated_open_documents(
    service: LanguageService,
) -> None:
    service.open_document('file:///defs.tcl', 'proc greet {name} {puts $name}\n', 1)
    diagnostics = service.open_document('file:///use.tcl', 'greet World\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert service.definition('file:///use.tcl', 0, 1) == ()
    assert service.hover('file:///use.tcl', 0, 1) is None

    references = service.references('file:///defs.tcl', 0, 5)
    assert {(location.uri, location.range.start.line) for location in references} == {
        ('file:///defs.tcl', 0),
    }


def test_language_service_hover_includes_proc_comment_blocks(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        '# Greets a user by name.\n# Returns nothing.\nproc greet {name} {puts $name}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet World\n',
        1,
    )

    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'


def test_language_service_loads_plugin_metadata_from_tcllsrc(tmp_path: Path) -> None:
    project_root = tmp_path / 'workspace'
    _write_sample_plugin_bundle(project_root / '.tcl-ls')
    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()


def test_language_service_loads_package_indexes_from_tcllsrc_lib_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    _write_sample_library_root(tmp_path / 'tcllib')
    project_root.mkdir()
    (project_root / 'tcllsrc.tcl').write_text(
        'lib-path ../tcllib\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'package require samplelib\nsamplelib::greet\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::samplelib::greet()'


def test_language_service_resolves_transitive_required_packages(tmp_path: Path) -> None:
    source_path = _write_transitive_package_workspace(tmp_path / 'workspace')
    source_text = source_path.read_text(encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command json::json2dict {jsonText}')
    assert '\n\n---\n\n' in hover.contents
    assert 'Imported via: helper -> json (transitive)' in hover.contents


def test_language_service_hover_omits_tcl_transitive_import_notes(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package require Tcl\npackage provide helper 1.0\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nclock seconds\n', 1)

    assert diagnostics == ()
    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command clock ')
    assert 'Imported via:' not in hover.contents


def test_language_service_uses_helper_metadata_for_embedded_dependencies(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    devtools_root = project_root / 'devtools'
    package_root = project_root / 'pkg'
    devtools_root.mkdir(parents=True)
    package_root.mkdir()

    (devtools_root / 'testutilities.tcl').write_text(
        'proc testing {script} {}\n'
        'proc useLocal {fname pname args} {}\n'
        'proc testsNeed {name {version {}}} {}\n',
        encoding='utf-8',
    )
    helper_path = package_root / 'helper.tcl'
    helper_path.write_text(
        'proc helper {} {return ok}\n',
        encoding='utf-8',
    )

    source_path = package_root / 'main.test'
    source_text = (
        'source [file join [file dirname [file dirname [info script]]] devtools testutilities.tcl]\n'
        'testing {\n'
        '    useLocal helper.tcl demo\n'
        '    testsNeed Tk 8.5\n'
        '}\n'
        'helper\n'
        'frame .f\n'
    )
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()

    helper_definitions = service.definition(source_path.as_uri(), 5, 1)
    assert len(helper_definitions) == 1
    assert helper_definitions[0].uri == helper_path.as_uri()

    hover = service.hover(source_path.as_uri(), 6, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command frame ')


def test_language_service_loads_generated_project_metadata_without_docs(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    _write_sample_plugin_bundle(project_root / '.tcl-ls')
    (project_root / '.tcl-ls' / 'generated.meta.tcl').write_text(
        'meta module Tcl\nmeta command external {args}\n',
        encoding='utf-8',
    )
    (project_root / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    source_path = project_root / 'main.tcl'
    source_text = 'external run\n'
    source_path.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    diagnostics = service.open_document(source_path.as_uri(), source_text, 1)

    assert diagnostics == ()
    hover = service.hover(source_path.as_uri(), 0, 1)
    assert hover is not None
    assert hover.contents == 'builtin command external {args}'


def test_language_service_clears_project_metadata_when_plugin_paths_change(
    tmp_path: Path,
) -> None:
    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    _write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    project_without_plugin.mkdir()

    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    assert service.open_document(source_with_plugin.as_uri(), source_text, 1) == ()

    service.close_document(source_with_plugin.as_uri())
    diagnostics = service.open_document(source_without_plugin.as_uri(), source_text, 1)

    assert len(diagnostics) == 2
    assert all(diagnostic.code == 'unresolved-command' for diagnostic in diagnostics)


def test_language_service_isolates_project_metadata_between_services(
    tmp_path: Path,
) -> None:
    project_with_plugin = tmp_path / 'with-plugin'
    project_without_plugin = tmp_path / 'without-plugin'
    _write_sample_plugin_bundle(project_with_plugin / '.tcl-ls')
    (project_with_plugin / 'tcllsrc.tcl').write_text(
        'plugin-path .tcl-ls/sample.tcl\n',
        encoding='utf-8',
    )
    project_without_plugin.mkdir()

    source_text = 'dsl::define greet {{name}} {puts $name}\ngreet World\n'
    source_with_plugin = project_with_plugin / 'main.tcl'
    source_with_plugin.write_text(source_text, encoding='utf-8')
    source_without_plugin = project_without_plugin / 'main.tcl'
    source_without_plugin.write_text(source_text, encoding='utf-8')

    service_with_plugin = LanguageService()
    service_without_plugin = LanguageService()

    assert service_with_plugin.open_document(source_with_plugin.as_uri(), source_text, 1) == ()

    diagnostics = service_without_plugin.open_document(
        source_without_plugin.as_uri(), source_text, 1
    )

    assert len(diagnostics) == 2
    assert all(diagnostic.code == 'unresolved-command' for diagnostic in diagnostics)

    hover = service_with_plugin.hover(source_with_plugin.as_uri(), 1, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)'


def test_language_service_clears_project_library_paths_when_project_changes(
    tmp_path: Path,
) -> None:
    project_with_lib = tmp_path / 'with-lib'
    project_without_lib = tmp_path / 'without-lib'
    _write_sample_library_root(tmp_path / 'tcllib')
    project_with_lib.mkdir()
    project_without_lib.mkdir()
    (project_with_lib / 'tcllsrc.tcl').write_text(
        'lib-path ../tcllib\n',
        encoding='utf-8',
    )

    source_text = 'package require samplelib\nsamplelib::greet\n'
    source_with_lib = project_with_lib / 'main.tcl'
    source_with_lib.write_text(source_text, encoding='utf-8')
    source_without_lib = project_without_lib / 'main.tcl'
    source_without_lib.write_text(source_text, encoding='utf-8')

    service = LanguageService()
    assert service.open_document(source_with_lib.as_uri(), source_text, 1) == ()

    service.close_document(source_with_lib.as_uri())
    diagnostics = service.open_document(source_without_lib.as_uri(), source_text, 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']


def test_language_service_definition_resolves_builtin_command_metadata(
    service: LanguageService,
) -> None:
    service.open_document(_MAIN_URI, 'set value 1\n', 1)

    builtin = builtin_command('set')
    assert builtin is not None

    definition_locations = service.definition(_MAIN_URI, 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0] == builtin.overloads[0].location


def test_language_service_definition_returns_all_builtin_overloads(
    service: LanguageService,
) -> None:
    service.open_document(_MAIN_URI, 'after 100\n', 1)

    builtin = builtin_command('after')
    assert builtin is not None

    definition_locations = service.definition(_MAIN_URI, 0, 1)
    assert definition_locations == tuple(overload.location for overload in builtin.overloads)


def test_language_service_definition_prefers_project_builtin_override_metadata(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / '.tcl-ls'
    plugin_root.mkdir()
    override_path = plugin_root / 'override.meta.tcl'
    override_path.write_text('meta module Tcl\nmeta command clock {args}\n', encoding='utf-8')
    (tmp_path / 'tcllsrc.tcl').write_text('plugin-path .tcl-ls\n', encoding='utf-8')

    source_path = tmp_path / 'main.tcl'
    source_text = 'clock foo\n'
    source_path.write_text(source_text, encoding='utf-8')

    assert service.open_document(source_path.as_uri(), source_text, 1) == ()

    definition_locations = service.definition(source_path.as_uri(), 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == override_path.as_uri()

    hover = service.hover(source_path.as_uri(), 0, 1)
    assert hover is not None
    assert hover.contents == 'builtin command clock {args}'


def test_language_service_definition_resolves_global_variable_links(
    service: LanguageService,
) -> None:
    service.open_document(
        _MAIN_URI,
        'set shared 0\nproc run {} {\n    global shared\n    incr shared\n    puts $shared\n}\n',
        1,
    )

    definition_locations = service.definition(_MAIN_URI, 4, 11)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 4

    hover = service.hover(_MAIN_URI, 4, 11)
    assert hover is not None
    assert hover.contents == 'set shared'


def test_language_service_definition_resolves_namespace_variable_links(
    service: LanguageService,
) -> None:
    service.open_document(
        _MAIN_URI,
        'namespace eval app {\n'
        '    variable counter 0\n'
        '    proc run {} {\n'
        '        variable counter\n'
        '        puts $counter\n'
        '    }\n'
        '}\n',
        1,
    )

    definition_locations = service.definition(_MAIN_URI, 4, 16)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == 1
    assert definition_locations[0].range.start.character == 13

    hover = service.hover(_MAIN_URI, 4, 16)
    assert hover is not None
    assert hover.contents == 'variable counter'


def test_language_service_definition_resolves_variable_alias_sites(
    service: LanguageService,
) -> None:
    service.open_document(
        _MAIN_URI,
        'namespace eval app {\n'
        '    variable counter\n'
        '    if {![info exists counter]} { set counter 0 }\n'
        '    proc run {} {\n'
        '        variable counter\n'
        '    }\n'
        '}\n',
        1,
    )

    alias_definition_locations = service.definition(_MAIN_URI, 4, 18)
    assert len(alias_definition_locations) == 1
    assert alias_definition_locations[0].uri == _MAIN_URI
    assert alias_definition_locations[0].range.start.line == 1
    assert alias_definition_locations[0].range.start.character == 13

    alias_hover = service.hover(_MAIN_URI, 4, 18)
    assert alias_hover is not None
    assert alias_hover.contents == 'variable counter'

    namespace_write_definition_locations = service.definition(_MAIN_URI, 2, 38)
    assert len(namespace_write_definition_locations) == 1
    assert namespace_write_definition_locations[0].uri == _MAIN_URI
    assert namespace_write_definition_locations[0].range.start.line == 1
    assert namespace_write_definition_locations[0].range.start.character == 13


def test_language_service_definition_resolves_dynamic_set_targets_from_foreach_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {strategy} {\n'
        '    foreach v {mode run_limit engines} {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    return_line = source_text.splitlines()[4]
    target_character = return_line.index('$engines') + 1
    definition_locations = service.definition(_MAIN_URI, 4, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == 2
    assert definition_locations[0].range.start.character == source_text.splitlines()[2].index('$v')

    hover = service.hover(_MAIN_URI, 4, target_character)
    assert hover is not None
    assert hover.contents == 'set engines'

    binding_hover = service.hover(_MAIN_URI, 2, source_text.splitlines()[2].index('$v') + 1)
    assert binding_hover is not None
    assert binding_hover.contents == 'set mode\nset run_limit\nset engines'


def test_language_service_definition_resolves_dynamic_set_targets_from_variable_backed_foreach_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {strategy} {\n'
        '    set names {mode run_limit engines}\n'
        '    set slots $names\n'
        '    foreach v $slots {\n'
        '        set $v [dict get $strategy $v]\n'
        '    }\n'
        '    return [list $mode $run_limit $engines]\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    return_line = source_text.splitlines()[6]
    target_character = return_line.index('$engines') + 1
    definition_locations = service.definition(_MAIN_URI, 6, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == 4
    assert definition_locations[0].range.start.character == source_text.splitlines()[4].index('$v')

    hover = service.hover(_MAIN_URI, 6, target_character)
    assert hover is not None
    assert hover.contents == 'set engines'


def test_language_service_preserves_switch_branch_list_body_positions_after_continuations(
    service: LanguageService,
) -> None:
    source_text = (
        'proc helper args {return ok}\n'
        'proc run {mode a b c d e} {\n'
        '    switch -regexp $mode {\n'
        '        "prepare" {\n'
        '            helper \\\n'
        '                -a $a \\\n'
        '                -b $b \\\n'
        '                -c $c \\\n'
        '                -d $d \\\n'
        '                -e $e\n'
        '        }\n'
        '        "mode_alpha" -\n'
        '        "mode_beta" -\n'
        '        "mode_gamma" -\n'
        '        "mode_[12]" {\n'
        '            set mapped_mode [switch $mode {\n'
        '              mode_1  {concat mode_beta}\n'
        '              mode_2  {concat mode_gamma}\n'
        '              default {concat $mode}\n'
        '            }]\n'
        '            puts $mapped_mode\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    set_line = source_text.splitlines().index('            set mapped_mode [switch $mode {')
    switch_character = source_text.splitlines()[set_line].index('switch') + 1
    hover = service.hover(_MAIN_URI, set_line, switch_character)
    assert hover is not None
    assert hover.contents.startswith('builtin command switch')

    puts_line = source_text.splitlines().index('            puts $mapped_mode')
    target_character = source_text.splitlines()[puts_line].index('$mapped_mode') + 1
    definition_locations = service.definition(_MAIN_URI, puts_line, target_character)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == set_line
    assert definition_locations[0].range.start.character == (
        source_text.splitlines()[set_line].index('mapped_mode')
    )


def test_language_service_hover_shows_branch_narrowed_values(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {} {\n'
        '    foreach kind {prove lint scan} {\n'
        '        if {$kind eq "prove"} {\n'
        '            puts $kind\n'
        '        } elseif {$kind eq "lint"} {\n'
        '            puts $kind\n'
        '        } else {\n'
        '            puts $kind\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    then_hover = service.hover(_MAIN_URI, 3, source_text.splitlines()[3].index('$kind') + 1)
    assert then_hover is not None
    assert then_hover.contents == 'foreach kind: "prove"'

    elseif_hover = service.hover(_MAIN_URI, 5, source_text.splitlines()[5].index('$kind') + 1)
    assert elseif_hover is not None
    assert elseif_hover.contents == 'foreach kind: "lint"'

    else_hover = service.hover(_MAIN_URI, 7, source_text.splitlines()[7].index('$kind') + 1)
    assert else_hover is not None
    assert else_hover.contents == 'foreach kind: "scan"'


def test_language_service_narrows_literal_regexp_switch_branch_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {mode} {\n'
        '    switch -regexp $mode {\n'
        '        "alpha" -\n'
        '        "beta" -\n'
        '        "gamma" {\n'
        '            switch $mode {\n'
        '                "alpha" { return first }\n'
        '                "beta" { return second }\n'
        '                "gamma" { return third }\n'
        '            }\n'
        '        }\n'
        '        "[de]lta" {\n'
        '            return fallback\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    inner_switch_line = source_text.splitlines().index('            switch $mode {')
    inner_switch_character = source_text.splitlines()[inner_switch_line].index('$mode') + 1
    hover = service.hover(_MAIN_URI, inner_switch_line, inner_switch_character)
    assert hover is not None
    assert hover.contents == 'parameter mode: "alpha" | "beta" | "gamma"'


def test_language_service_hover_shows_switch_assignment_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {mode} {\n'
        '    switch -regexp $mode {\n'
        '        "direct_alpha" -\n'
        '        "direct_beta" -\n'
        '        "mode_1" -\n'
        '        "mode_2" {\n'
        '            set mapped_mode [switch $mode {\n'
        '                mode_1 {concat target_alpha}\n'
        '                mode_2 {concat target_beta}\n'
        '                default {concat $mode}\n'
        '            }]\n'
        '            puts $mapped_mode\n'
        '        }\n'
        '        "[fg].*" {\n'
        '            return fallback\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    binding_line = source_text.splitlines().index('            set mapped_mode [switch $mode {')
    binding_character = source_text.splitlines()[binding_line].index('mapped_mode') + 1
    binding_hover = service.hover(_MAIN_URI, binding_line, binding_character)
    assert binding_hover is not None
    assert (
        binding_hover.contents
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )

    reference_line = source_text.splitlines().index('            puts $mapped_mode')
    reference_character = source_text.splitlines()[reference_line].index('$mapped_mode') + 1
    reference_hover = service.hover(_MAIN_URI, reference_line, reference_character)
    assert reference_hover is not None
    assert (
        reference_hover.contents
        == 'set mapped_mode: "target_alpha" | "target_beta" | "direct_alpha" | "direct_beta"'
    )


def test_language_service_hover_shows_expr_ternary_assignment_domains(
    service: LanguageService,
) -> None:
    source_text = (
        'proc run {} {\n'
        '    foreach bg {0 1} {\n'
        '        set bg_opt [expr {$bg == 1 ? "a" : "b"}]\n'
        '        puts $bg_opt\n'
        '    }\n'
        '}\n'
    )
    assert service.open_document(_MAIN_URI, source_text, 1) == ()

    hover = service.hover(_MAIN_URI, 3, source_text.splitlines()[3].index('$bg_opt') + 1)
    assert hover is not None
    assert hover.contents == 'set bg_opt: "a" | "b"'

    binding_hover = service.hover(_MAIN_URI, 2, source_text.splitlines()[2].index('bg_opt') + 1)
    assert binding_hover is not None
    assert binding_hover.contents == 'set bg_opt: "a" | "b"'


def test_language_service_rename_updates_proc_declaration_and_calls(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {name} {return $name}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet World\n',
        1,
    )

    edits = service.rename(main_uri, 1, 1, 'welcome')

    assert edits is not None
    assert set(edits) == {helper_path.as_uri(), main_uri}
    assert edits[helper_path.as_uri()][0].span.start.line == 0
    assert edits[helper_path.as_uri()][0].span.start.character == 5
    assert edits[helper_path.as_uri()][0].new_text == 'welcome'
    assert edits[main_uri][0].span.start.line == 1
    assert edits[main_uri][0].span.start.character == 0
    assert edits[main_uri][0].new_text == 'welcome'


def test_language_service_rename_updates_variable_bindings_and_references(
    service: LanguageService,
) -> None:
    service.open_document(
        _MAIN_URI,
        'proc run {value} {\n    set local $value\n    puts $local\n}\n',
        1,
    )

    edits = service.rename(_MAIN_URI, 1, 9, 'item')

    assert edits is not None
    assert tuple(edits) == (_MAIN_URI,)
    assert [
        (edit.span.start.line, edit.span.start.character, edit.new_text)
        for edit in edits[_MAIN_URI]
    ] == [
        (1, 8, 'item'),
        (2, 9, '$item'),
    ]


def test_language_server_hover_uses_markdown_code_fences_for_signatures(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        '# Greets a user by name.\nproc greet {name} {puts $name}\ngreet World\n',
    )

    hover_value = _hover_markdown_value(server, line=2, character=1)
    assert hover_value == '```tcl\nproc ::greet(name)\n```\n\nGreets a user by name.'


def test_language_server_initialize_advertises_semantic_tokens() -> None:
    server = _fresh_server()
    response = _as_dict(
        process_message(
            server,
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        )[0]
    )

    capabilities = _as_dict(_as_dict(response['result'])['capabilities'])
    semantic_tokens = _as_dict(capabilities['semanticTokensProvider'])
    legend = _as_dict(semantic_tokens['legend'])

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
    assert legend['tokenModifiers'] == ['declaration', 'defaultLibrary']
    assert semantic_tokens['full'] == {'delta': True}
    assert capabilities['renameProvider'] is True
    completion_provider = _as_dict(capabilities['completionProvider'])
    assert completion_provider['triggerCharacters'] == ['$', ':']
    signature_help_provider = _as_dict(capabilities['signatureHelpProvider'])
    assert signature_help_provider['triggerCharacters'] == [' ', '\t']
    assert capabilities['documentHighlightProvider'] is True
    workspace_symbol_provider = _as_dict(capabilities['workspaceSymbolProvider'])
    assert workspace_symbol_provider == {'resolveProvider': False}


def test_language_server_returns_command_completion_items(server: LanguageServer) -> None:
    _open_server_document(server, 'proc greet {} {return ok}\ngr\n')

    items = _completion_items(server, line=1, character=2)
    greet_item = next(item for item in items if item['label'] == 'greet')

    assert greet_item['detail'] == 'proc ::greet()'


def test_language_server_returns_variable_completion_items(server: LanguageServer) -> None:
    source_text = 'proc run {value} {\n    set local $value\n    puts $\n}\n'
    _open_server_document(server, source_text)

    line = source_text.splitlines()[2]
    items = _completion_items(
        server,
        line=2,
        character=line.index('$') + 1,
    )

    item_by_label = {cast(str, item['label']): item for item in items}
    assert item_by_label['local']['detail'] == 'set local'
    assert item_by_label['value']['detail'] == 'parameter value'


def test_language_server_returns_package_completion_items(
    server: LanguageServer, tmp_path: Path
) -> None:
    project_root = tmp_path / 'workspace'
    _write_sample_library_root(tmp_path / 'tcllib')
    project_root.mkdir()
    (project_root / 'tcllsrc.tcl').write_text('lib-path ../tcllib\n', encoding='utf-8')

    source_path = project_root / 'main.tcl'
    source_text = 'package require sa\n'
    source_path.write_text(source_text, encoding='utf-8')

    _open_server_document(server, source_text, uri=source_path.as_uri())

    items = _completion_items(
        server,
        uri=source_path.as_uri(),
        line=0,
        character=len('package require sa'),
    )
    samplelib_item = next(item for item in items if item['label'] == 'samplelib')

    assert samplelib_item['detail'] == 'workspace package'


def test_language_server_returns_proc_signature_help(server: LanguageServer) -> None:
    _open_server_document(server, 'proc greet {name times} {return ok}\ngreet \n')

    result = _signature_help_result(server, line=1, character=len('greet '))

    assert result is not None
    signatures = cast(list[dict[str, object]], result['signatures'])
    assert signatures[0]['label'] == 'proc ::greet(name, times)'
    assert result['activeSignature'] == 0
    assert result['activeParameter'] == 0


def test_language_server_returns_builtin_signature_help(server: LanguageServer) -> None:
    _open_server_document(server, 'set \n')

    result = _signature_help_result(server, line=0, character=len('set '))

    assert result is not None
    signatures = cast(list[dict[str, object]], result['signatures'])
    assert signatures[0]['label'] == 'set {varName ? newValue ?}'
    assert result['activeParameter'] is None


def test_language_server_returns_document_highlights(server: LanguageServer) -> None:
    source_text = 'proc run {value} {\n    set local $value\n    puts $local\n}\n'
    _open_server_document(server, source_text)

    line = source_text.splitlines()[2]
    response = _server_position_request(
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

    _open_server_document(server, source_text, uri=main_path.as_uri())

    response = _server_workspace_request(
        server,
        method='workspace/symbol',
        params={'query': 'greet'},
    )
    result = cast(list[dict[str, object]], response['result'])

    greet_symbol = next(symbol for symbol in result if symbol['name'] == '::greet')
    location = _as_dict(greet_symbol['location'])
    assert location['uri'] == helper_path.as_uri()


def test_language_server_returns_semantic_tokens(server: LanguageServer) -> None:
    _open_server_document(
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

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    expected_tokens = (
        _semantic_token(line=0, character=0, length=5, token_type='comment'),
        _semantic_token(line=1, character=0, length=9, token_type='keyword'),
        _semantic_token(line=1, character=10, length=4, token_type='keyword'),
        _semantic_token(
            line=1,
            character=15,
            length=3,
            token_type='namespace',
            modifiers=['declaration'],
        ),
        _semantic_token(line=2, character=4, length=4, token_type='keyword'),
        _semantic_token(
            line=2,
            character=9,
            length=5,
            token_type='function',
            modifiers=['declaration'],
        ),
        _semantic_token(
            line=2,
            character=16,
            length=4,
            token_type='parameter',
            modifiers=['declaration'],
        ),
        _semantic_token(line=3, character=8, length=3, token_type='keyword'),
        _semantic_token(
            line=3,
            character=12,
            length=5,
            token_type='variable',
            modifiers=['declaration'],
        ),
        _semantic_token(line=3, character=19, length=4, token_type='parameter'),
        _semantic_token(
            line=4,
            character=8,
            length=4,
            token_type='function',
            modifiers=['defaultLibrary'],
        ),
        _semantic_token(line=4, character=14, length=5, token_type='variable'),
        _semantic_token(line=7, character=0, length=10, token_type='function'),
    )

    for expected_token in expected_tokens:
        assert expected_token in decoded


def test_language_server_returns_semantic_token_deltas(server: LanguageServer) -> None:
    initial_text = 'proc greet {} {\n    return ok\n}\n'
    changed_text = '\nproc greet {} {\n    return ok\n}\n'

    def skip_document_change(uri: str, version: int) -> None:
        del uri, version

    _open_server_document(server, initial_text)

    initial_response = _server_document_request(server, method='textDocument/semanticTokens/full')
    initial_result = _as_dict(initial_response['result'])
    initial_data = cast(list[int], initial_result['data'])
    previous_result_id = cast(str, initial_result['resultId'])

    original_schedule_document_change = server.schedule_document_change
    try:
        _override_schedule_document_change(server, skip_document_change)
        _change_server_document(server, changed_text)

        delta_response = _server_semantic_token_delta_request(
            server,
            previous_result_id=previous_result_id,
        )
    finally:
        _override_schedule_document_change(server, original_schedule_document_change)

    delta_result = _as_dict(delta_response['result'])
    edits = cast(list[dict[str, object]], delta_result['edits'])
    updated_data = _apply_semantic_token_edits(initial_data, edits)

    latest_response = _server_document_request(
        server,
        method='textDocument/semanticTokens/full',
        request_id=2,
    )
    latest_result = _as_dict(latest_response['result'])
    latest_data = cast(list[int], latest_result['data'])

    assert updated_data == latest_data
    assert delta_result['resultId'] == latest_result['resultId']

    token_types, token_modifiers = _semantic_tokens_legend(server)
    decoded = _decode_semantic_tokens(
        updated_data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert _semantic_token(line=1, character=0, length=4, token_type='keyword') in decoded
    assert (
        _semantic_token(
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
    _open_server_document(server, 'proc greet {} {\n    return ok\n}\n')

    delta_response = _server_semantic_token_delta_request(
        server,
        previous_result_id='unknown-result',
    )
    delta_result = _as_dict(delta_response['result'])

    full_response = _server_document_request(
        server,
        method='textDocument/semanticTokens/full',
        request_id=2,
    )
    full_result = _as_dict(full_response['result'])

    assert delta_result['data'] == full_result['data']
    assert delta_result['resultId'] == full_result['resultId']
    assert 'edits' not in delta_result


def test_language_server_returns_semantic_tokens_for_embedded_comments_and_if_keywords(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        'proc greet {} {\n'
        '    if {1} then {\n'
        '        # then comment\n'
        '    } else {\n'
        '        # else comment\n'
        '    }\n'
        '}\n',
    )

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
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
    _open_server_document(
        server,
        'proc greet {name} {\n    if {1} {\n        puts "hello [string trim $name]"\n    }\n}\n',
    )

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        _semantic_token(line=0, character=18, length=1, token_type='operator'),
        _semantic_token(line=1, character=11, length=1, token_type='operator'),
        _semantic_token(line=2, character=13, length=1, token_type='string'),
        _semantic_token(line=2, character=14, length=6, token_type='string'),
        _semantic_token(line=2, character=20, length=1, token_type='operator'),
        _semantic_token(line=2, character=38, length=1, token_type='operator'),
        _semantic_token(line=2, character=39, length=1, token_type='string'),
        _semantic_token(line=3, character=4, length=1, token_type='operator'),
        _semantic_token(line=4, character=0, length=1, token_type='operator'),
    ):
        assert expected_token in decoded


def test_language_server_returns_semantic_tokens_for_return_keyword(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        'proc greet {} {\n    return ok\n}\n',
    )

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert _semantic_token(line=1, character=4, length=6, token_type='keyword') in decoded


def test_language_server_returns_semantic_tokens_for_semicolons(
    server: LanguageServer,
) -> None:
    _open_server_document(server, 'set first 1; set second 2\n')

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    assert _semantic_token(line=0, character=11, length=1, token_type='operator') in decoded


def test_language_server_returns_semantic_tokens_for_nested_delimiters_in_braced_words(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        'proc init {{httpproxy {}}} {\n'
        '    if {! [info exists options]} {\n'
        '        switch -- $mode {\n'
        '            default { return [list {}] }\n'
        '        }\n'
        '    }\n'
        '}\n',
    )

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        _semantic_token(line=0, character=22, length=1, token_type='operator'),
        _semantic_token(line=0, character=23, length=1, token_type='operator'),
        _semantic_token(line=1, character=10, length=1, token_type='operator'),
        _semantic_token(line=1, character=30, length=1, token_type='operator'),
        _semantic_token(line=3, character=20, length=1, token_type='operator'),
        _semantic_token(line=3, character=29, length=1, token_type='operator'),
        _semantic_token(line=3, character=35, length=1, token_type='operator'),
        _semantic_token(line=3, character=36, length=1, token_type='operator'),
        _semantic_token(line=3, character=37, length=1, token_type='operator'),
        _semantic_token(line=3, character=39, length=1, token_type='operator'),
    ):
        assert expected_token in decoded


def test_language_server_returns_semantic_tokens_for_braced_variable_substitutions(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        'set value ${name}\nputs ${value}\n',
    )

    token_types, token_modifiers = _semantic_tokens_legend(server)
    response = _server_document_request(server, method='textDocument/semanticTokens/full')
    result = _as_dict(response['result'])
    data = cast(list[int], result['data'])

    decoded = _decode_semantic_tokens(
        data,
        token_types=token_types,
        token_modifiers=token_modifiers,
    )

    for expected_token in (
        _semantic_token(line=0, character=11, length=1, token_type='operator'),
        _semantic_token(line=0, character=16, length=1, token_type='operator'),
        _semantic_token(line=1, character=6, length=1, token_type='operator'),
        _semantic_token(line=1, character=12, length=1, token_type='operator'),
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

    _open_server_document(server, initial_text)
    original_schedule_document_change = server.schedule_document_change
    try:
        _override_schedule_document_change(server, skip_document_change)
        _change_server_document(server, changed_text)

        token_types, token_modifiers = _semantic_tokens_legend(server)
        response = _server_document_request(server, method='textDocument/semanticTokens/full')
        result = _as_dict(response['result'])
        data = cast(list[int], result['data'])

        decoded = _decode_semantic_tokens(
            data,
            token_types=token_types,
            token_modifiers=token_modifiers,
        )

        assert (
            _semantic_token(
                line=expected_line,
                character=0,
                length=4,
                token_type='keyword',
            )
            in decoded
        )
        assert (
            _semantic_token(
                line=expected_line,
                character=5,
                length=5,
                token_type='function',
                modifiers=['declaration'],
            )
            in decoded
        )
    finally:
        _override_schedule_document_change(server, original_schedule_document_change)


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
    _open_server_document(server, text)

    hover_value = _hover_markdown_value(server, line=0, character=1)
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
    _open_server_document(server, source_text)

    hover_value = _hover_markdown_value(
        server,
        line=2,
        character=source_text.splitlines()[2].index('$v') + 1,
    )
    assert hover_value == '```tcl\nset mode\nset run_limit\nset engines\n```'


@pytest.mark.parametrize(
    ('text', 'character', 'builtin_name'),
    [
        ('namespace current\n', 11, 'namespace current'),
        ('dict get {a 1} a\n', 6, 'dict get'),
        ('trace add command foo delete cb\n', 12, 'trace add command'),
        ('binary encode base64 data\n', 15, 'binary encode base64'),
    ],
)
def test_language_service_definition_resolves_builtin_subcommand_metadata(
    service: LanguageService,
    text: str,
    character: int,
    builtin_name: str,
) -> None:
    service.open_document(_MAIN_URI, text, 1)

    builtin = builtin_command(builtin_name)
    assert builtin is not None
    assert len(builtin.overloads) == 1

    definition_locations = service.definition(_MAIN_URI, 0, character)
    assert len(definition_locations) == 1
    assert definition_locations[0] == builtin.overloads[0].location


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
    _open_server_document(server, text)

    builtin = builtin_command(builtin_name)
    assert builtin is not None
    assert len(builtin.overloads) == 1
    overload = builtin.overloads[0]
    heading = overload.signature.removesuffix(' {}')

    hover_value = _hover_markdown_value(server, line=0, character=character)
    assert hover_value == f'```tcl\n{heading}\n```\n\n{overload.documentation}'


def test_language_service_infers_packages_from_pkgindex(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == (helper_dir / 'helper.tcl').as_uri()

    hover = service.hover(main_uri, 1, 2)
    assert hover is not None
    assert hover.contents == 'proc ::helper::greet()'


def test_language_service_definition_resolves_required_package_to_provider(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 0, 17)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 16


def test_language_service_hover_notes_imported_package_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (helper_dir / 'helper.tcl').write_text(
        'package provide helper 1.0\n# Greets helper callers.\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'package require helper\nnamespace import ::helper::*\ngreet\n',
        1,
    )

    assert diagnostics == ()
    hover = service.hover(main_uri, 2, 1)
    assert hover is not None
    assert (
        hover.contents
        == 'proc ::helper::greet()\n\nGreets helper callers.\n\n---\n\nImported via: ::helper::*'
    )


def test_language_service_definition_resolves_namespace_import_patterns(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    modules_root = tmp_path / 'workspace' / 'modules'
    helper_dir = modules_root / 'helper'
    app_dir = modules_root / 'app'
    helper_dir.mkdir(parents=True)
    app_dir.mkdir()

    (helper_dir / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    helper_path = helper_dir / 'helper.tcl'
    helper_path.write_text(
        'package provide helper 1.0\nproc helper::greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'package require helper\nnamespace import ::helper::*\n',
        1,
    )

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 20)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()
    assert definition_locations[0].range.start.line == 1
    assert definition_locations[0].range.start.character == 5


def test_language_service_loads_static_source_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
        1,
    )

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == helper_path.as_uri()

    hover = service.hover(main_uri, 1, 2)
    assert hover is not None
    assert hover.contents == 'proc ::greet()'


def test_language_service_unloads_removed_static_source_commands(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    assert (
        service.open_document(
            main_uri,
            'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
            1,
        )
        == ()
    )

    diagnostics = service.change_document(main_uri, 'greet\n', 2)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert diagnostics[0].message == 'Unresolved command `greet`.'


def test_language_service_removed_static_source_ignores_other_open_helper_window(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    helper_path = project_root / 'helper.inc'
    helper_path.write_text(
        'proc greet {} {return ok}\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.tcl').as_uri()
    helper_uri = helper_path.as_uri()
    assert (
        service.open_document(
            main_uri,
            'source [file join [file dirname [info script]] helper.inc]\ngreet\n',
            1,
        )
        == ()
    )
    assert service.open_document(helper_uri, helper_path.read_text(encoding='utf-8'), 1) == ()

    diagnostics = service.change_document(main_uri, 'greet\n', 2)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-command']
    assert diagnostics[0].message == 'Unresolved command `greet`.'


def test_language_service_resolves_sourced_tcltest_imports(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'workspace'
    project_root.mkdir()
    (project_root / 'helper.inc').write_text(
        'package require tcltest\nnamespace import -force ::tcltest::*\n',
        encoding='utf-8',
    )

    main_uri = (project_root / 'main.test').as_uri()
    diagnostics = service.open_document(
        main_uri,
        'source [file join [file dirname [info script]] helper.inc]\n'
        'test demo {} -body {return ok}\n'
        '::tcltest::cleanupTests\n',
        1,
    )

    assert diagnostics == ()

    hover = service.hover(main_uri, 1, 1)
    assert hover is not None
    assert hover.contents.startswith('builtin command tcltest::test')
    assert 'Imported via: helper.inc -> ::tcltest::*' in hover.contents
    assert 'Imported via: helper.inc -> tcltest (transitive)' in hover.contents

    qualified_hover = service.hover(main_uri, 2, 3)
    assert qualified_hover is not None
    assert qualified_hover.contents.startswith('builtin command tcltest::cleanupTests')
    assert 'Imported via: helper.inc -> tcltest (transitive)' in qualified_hover.contents


def test_language_service_analyzes_catch_bodies_and_result_variables(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        _MAIN_URI,
        'proc helper {} {return ok}\n'
        'proc run {} {\n'
        '    catch {\n'
        '        set local [helper]\n'
        '    } message options\n'
        '    puts $message\n'
        '    puts $options\n'
        '    puts $local\n'
        '}\n',
        1,
    )

    assert diagnostics == ()


def test_language_service_resolves_references_inside_braced_if_conditions(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        _MAIN_URI,
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {$flag && [helper]} {\n'
        '        return ok\n'
        '    }\n'
        '}\n',
        1,
    )

    assert diagnostics == ()

    hover = service.hover(_MAIN_URI, 2, 9)
    assert hover is not None
    assert hover.contents == 'parameter flag'

    definition_locations = service.definition(_MAIN_URI, 2, 18)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == _MAIN_URI
    assert definition_locations[0].range.start.line == 0
    assert definition_locations[0].range.start.character == 5


def test_language_service_reports_unresolved_packages(
    service: LanguageService,
    tmp_path: Path,
) -> None:
    main_uri = (tmp_path / 'missing.tcl').as_uri()

    diagnostics = service.open_document(main_uri, 'package require missing\nmissing::run\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']


def test_language_service_does_not_report_meta_guard_commands_as_unresolved(
    service: LanguageService,
) -> None:
    diagnostics = service.open_document(
        'file:///meta_file.tcl',
        'if {[llength [info commands meta]] == 0} {\n'
        '    proc meta {args} {}\n'
        '}\n'
        '# Builtin metadata entry.\n'
        'meta command after {ms}\n',
        1,
    )

    assert diagnostics == ()


def test_language_server_hover_formats_meta_builtin_command(server: LanguageServer) -> None:
    _open_server_document(server, 'meta command after {ms}\n')

    hover_value = _hover_markdown_value(server, line=0, character=1)
    assert hover_value.startswith('```tcl\nmeta {subcommand args}\n```\n\n')
    assert 'Top-level declarations:' in hover_value
    assert 'structured documentation instead of executable behavior' in hover_value.replace(
        '\n', ' '
    )
    assert 'option name value' in hover_value


def test_language_server_process_message_publishes_diagnostics(server: LanguageServer) -> None:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///diag.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc greet {} {puts $name}\n',
                }
            },
        },
    )

    assert len(messages) == 3
    show_message = messages[0]
    assert show_message['method'] == 'window/showMessage'
    show_params = _as_dict(show_message['params'])
    assert show_params['type'] == 3
    assert show_params['message'] == 'Indexing workspace.'

    log_message = messages[1]
    assert log_message['method'] == 'window/logMessage'
    log_params = _as_dict(log_message['params'])
    assert log_params['type'] == 3
    assert log_params['message'] == 'Indexing workspace for file:///diag.tcl.'

    publish = messages[2]
    assert publish['method'] == 'textDocument/publishDiagnostics'
    params = _as_dict(publish['params'])
    assert params['uri'] == 'file:///diag.tcl'
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']


def test_language_server_process_message_coalesces_stale_document_changes(
    server: LanguageServer,
) -> None:
    class SlowChangeService:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.finished = threading.Event()
            self.versions: list[int] = []

        def change_document(
            self,
            uri: str,
            text: str,
            version: int,
            *,
            should_cancel: Callable[[], bool] | None = None,
        ) -> tuple[Diagnostic, ...] | None:
            del uri, text
            self.versions.append(version)
            if version == 2:
                self.started.set()
                deadline = time.monotonic() + 1
                while should_cancel is not None and not should_cancel():
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                return None

            self.finished.set()
            return (
                Diagnostic(
                    span=Span(
                        start=Position(offset=0, line=0, character=0),
                        end=Position(offset=1, line=0, character=1),
                    ),
                    severity='error',
                    message='latest version',
                    source='test',
                    code='latest-only',
                ),
            )

    def send(message: dict[str, object]) -> None:
        structured = cast(RPCMessage, server.protocol.structure_message(message))
        server.protocol.handle_message(structured)

    _open_server_document(server, 'puts ok\n')

    output_stream = _NonClosingBytesIO()
    server.protocol.set_writer(_CaptureWriter(output_stream))

    service = SlowChangeService()
    _override_change_document(server, service.change_document)

    send(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': _MAIN_URI, 'version': 2},
                'contentChanges': [{'text': 'puts first\n'}],
            },
        }
    )
    assert service.started.wait(timeout=1)

    send(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': _MAIN_URI, 'version': 3},
                'contentChanges': [{'text': 'puts latest\n'}],
            },
        }
    )
    assert service.finished.wait(timeout=1)

    deadline = time.monotonic() + 1
    publish_messages: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        publish_messages = [
            message
            for message in _decode_frames(output_stream.getvalue())
            if message.get('method') == 'textDocument/publishDiagnostics'
        ]
        if publish_messages:
            break
        time.sleep(0.01)

    assert service.versions == [2, 3]
    assert len(publish_messages) == 1
    params = _as_dict(publish_messages[0]['params'])
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])
    assert diagnostics == [
        {
            'range': {
                'start': {'line': 0, 'character': 0},
                'end': {'line': 0, 'character': 1},
            },
            'severity': types.DiagnosticSeverity.Error,
            'code': 'latest-only',
            'source': 'test',
            'message': 'latest version',
        }
    ]


def test_language_server_process_message_logs_startup(server: LanguageServer) -> None:
    messages = process_message(server, {'jsonrpc': '2.0', 'method': 'initialized', 'params': {}})

    assert len(messages) == 1
    log_notification = messages[0]
    assert log_notification['method'] == 'window/logMessage'
    params = _as_dict(log_notification['params'])
    assert params == {'type': 3, 'message': 'tcl-ls started.'}


def test_language_server_process_message_reports_indexing_progress_when_supported() -> None:
    server = _fresh_server()
    process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'capabilities': {'window': {'workDoneProgress': True}}},
        },
    )

    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///diag.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc greet {} {puts $name}\n',
                }
            },
        },
    )

    assert [message['method'] for message in messages] == [
        'window/workDoneProgress/create',
        '$/progress',
        '$/progress',
        '$/progress',
        '$/progress',
        '$/progress',
        'window/logMessage',
        'textDocument/publishDiagnostics',
        '$/progress',
    ]
    create_request = messages[0]
    assert create_request['id'] == 'tcl-ls/request/1'
    assert _as_dict(create_request['params']) == {'token': 'tcl-ls/indexing/1'}

    begin_params = _as_dict(messages[1]['params'])
    assert begin_params['token'] == 'tcl-ls/indexing/1'
    begin_value = _as_dict(begin_params['value'])
    assert begin_value == {
        'kind': 'begin',
        'title': 'Indexing workspace',
        'message': 'Starting analysis',
        'percentage': 0,
    }

    report_values = [_as_dict(_as_dict(message['params'])['value']) for message in messages[2:6]]
    assert report_values == [
        {'kind': 'report', 'message': 'Rebuilding workspace index', 'percentage': 10},
        {'kind': 'report', 'message': 'Indexing workspace files (1/1)', 'percentage': 45},
        {'kind': 'report', 'message': 'Loading workspace dependencies', 'percentage': 50},
        {'kind': 'report', 'message': 'Analyzing workspace (1/1)', 'percentage': 95},
    ]

    log_params = _as_dict(messages[6]['params'])
    assert log_params == {'type': 3, 'message': 'Indexing workspace for file:///diag.tcl.'}

    diagnostics = cast(list[dict[str, object]], _as_dict(messages[7]['params'])['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']

    end_params = _as_dict(messages[8]['params'])
    assert end_params['token'] == 'tcl-ls/indexing/1'
    end_value = _as_dict(end_params['value'])
    assert end_value == {'kind': 'end', 'message': 'Indexing complete.'}


def test_language_server_process_message_shows_indexing_only_once(
    server: LanguageServer,
) -> None:
    first_messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///first.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
    )
    second_messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///second.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
    )

    assert [message['method'] for message in first_messages] == [
        'window/showMessage',
        'window/logMessage',
        'textDocument/publishDiagnostics',
    ]
    assert [message['method'] for message in second_messages] == [
        'window/logMessage',
        'textDocument/publishDiagnostics',
    ]


def test_language_server_process_message_renames_symbols(server: LanguageServer) -> None:
    _open_server_document(server, 'proc greet {} {return ok}\ngreet\n')

    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 8,
            'method': 'textDocument/rename',
            'params': {
                'textDocument': {'uri': _MAIN_URI},
                'position': {'line': 1, 'character': 1},
                'newName': 'welcome',
            },
        },
    )

    assert len(messages) == 1
    response = messages[0]
    assert response['id'] == 8
    result = _as_dict(response['result'])
    changes = cast(dict[str, list[dict[str, object]]], result['changes'])
    assert tuple(changes) == (_MAIN_URI,)
    assert changes[_MAIN_URI] == [
        {
            'range': {
                'start': {'line': 0, 'character': 5},
                'end': {'line': 0, 'character': 10},
            },
            'newText': 'welcome',
        },
        {
            'range': {
                'start': {'line': 1, 'character': 0},
                'end': {'line': 1, 'character': 5},
            },
            'newText': 'welcome',
        },
    ]


def test_language_server_start_io_round_trip() -> None:
    input_stream = BytesIO()
    output_stream = _NonClosingBytesIO()
    server = _fresh_server()

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': _MAIN_URI,
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc greet {name} {puts $name}\ngreet World\n',
                }
            },
        },
        {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'textDocument/definition',
            'params': {
                'textDocument': {'uri': _MAIN_URI},
                'position': {'line': 1, 'character': 1},
            },
        },
        {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown', 'params': {}},
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(_encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    server.start_io(input_stream, output_stream)

    messages = _decode_frames(output_stream.getvalue())
    initialize_response = next(message for message in messages if message.get('id') == 1)
    initialize_result = _as_dict(initialize_response['result'])
    capabilities = _as_dict(initialize_result['capabilities'])
    assert capabilities['definitionProvider'] is True

    diagnostics_notification = next(
        message
        for message in messages
        if message.get('method') == 'textDocument/publishDiagnostics'
    )
    diagnostics_params = _as_dict(diagnostics_notification['params'])
    assert diagnostics_params['diagnostics'] == []

    definition_response = next(message for message in messages if message.get('id') == 2)
    definition_results = cast(list[dict[str, object]], definition_response['result'])
    definition_range = _as_dict(definition_results[0]['range'])
    assert definition_results[0]['uri'] == _MAIN_URI
    assert definition_range['start'] == {'line': 0, 'character': 5}

    shutdown_response = next(message for message in messages if message.get('id') == 3)
    assert shutdown_response['result'] is None


def test_language_server_start_io_emits_indexing_notification_before_open_finishes() -> None:
    class BlockingService:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.finish = threading.Event()

        def open_document(
            self,
            uri: str,
            text: str,
            version: int,
            *,
            progress: Callable[[str, int], None] | None = None,
        ) -> tuple[object, ...]:
            self.started.set()
            assert self.finish.wait(timeout=1)
            return ()

    service = BlockingService()
    input_stream = BytesIO()
    output_stream = _NonClosingBytesIO()
    server = _fresh_server()
    _override_open_document(server, service.open_document)

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': _MAIN_URI,
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(_encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    thread = threading.Thread(target=server.start_io, args=(input_stream, output_stream))
    thread.start()

    assert service.started.wait(timeout=1)
    messages = _decode_frames(output_stream.getvalue())
    show_messages = [
        message for message in messages if message.get('method') == 'window/showMessage'
    ]
    assert show_messages == [
        {
            'jsonrpc': '2.0',
            'method': 'window/showMessage',
            'params': {'type': 3, 'message': 'Indexing workspace.'},
        }
    ]

    service.finish.set()
    thread.join(timeout=1)
    assert thread.is_alive() is False


def test_language_server_start_io_emits_indexing_progress_before_open_finishes() -> None:
    class BlockingService:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.finish = threading.Event()

        def open_document(
            self,
            uri: str,
            text: str,
            version: int,
            *,
            progress: Callable[[str, int], None] | None = None,
        ) -> tuple[object, ...]:
            if progress is not None:
                progress('Indexing open documents', 20)
            self.started.set()
            assert self.finish.wait(timeout=1)
            if progress is not None:
                progress('Analyzing workspace (1/1)', 95)
            return ()

    service = BlockingService()
    input_stream = BytesIO()
    output_stream = _NonClosingBytesIO()
    server = _fresh_server()
    _override_open_document(server, service.open_document)

    frames: list[dict[str, object]] = [
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'capabilities': {'window': {'workDoneProgress': True}}},
        },
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': _MAIN_URI,
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(_encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    thread = threading.Thread(target=server.start_io, args=(input_stream, output_stream))
    thread.start()

    assert service.started.wait(timeout=1)
    progress_messages = [
        message
        for message in _decode_frames(output_stream.getvalue())
        if message.get('method') in {'window/workDoneProgress/create', '$/progress'}
    ]
    assert progress_messages == [
        {
            'jsonrpc': '2.0',
            'id': 'tcl-ls/request/1',
            'method': 'window/workDoneProgress/create',
            'params': {'token': 'tcl-ls/indexing/1'},
        },
        {
            'jsonrpc': '2.0',
            'method': '$/progress',
            'params': {
                'token': 'tcl-ls/indexing/1',
                'value': {
                    'kind': 'begin',
                    'title': 'Indexing workspace',
                    'message': 'Starting analysis',
                    'percentage': 0,
                },
            },
        },
        {
            'jsonrpc': '2.0',
            'method': '$/progress',
            'params': {
                'token': 'tcl-ls/indexing/1',
                'value': {
                    'kind': 'report',
                    'message': 'Indexing open documents',
                    'percentage': 20,
                },
            },
        },
    ]

    service.finish.set()
    thread.join(timeout=1)
    assert thread.is_alive() is False


def _encode_frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
    header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
    return header + payload


def _decode_frames(payload: bytes) -> list[dict[str, object]]:
    index = 0
    messages: list[dict[str, object]] = []

    while index < len(payload):
        header_end = payload.index(b'\r\n\r\n', index)
        header_block = payload[index:header_end].decode('ascii')
        index = header_end + 4

        content_length = 0
        for header_line in header_block.split('\r\n'):
            if header_line.lower().startswith('content-length:'):
                content_length = int(header_line.split(':', maxsplit=1)[1].strip())
                break

        message_bytes = payload[index : index + content_length]
        index += content_length
        messages.append(_as_dict(json.loads(message_bytes.decode('utf-8'))))

    return messages


def _as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
