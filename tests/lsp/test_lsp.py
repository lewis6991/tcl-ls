from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.lsp import LanguageServer, LanguageService

_MAIN_URI = 'file:///main.tcl'


def _open_server_document(
    server: LanguageServer,
    text: str,
    *,
    uri: str = _MAIN_URI,
    version: int = 1,
) -> None:
    server.process_message(
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
        }
    )


def _server_position_request(
    server: LanguageServer,
    *,
    method: str,
    line: int,
    character: int,
    uri: str = _MAIN_URI,
    request_id: int = 1,
) -> dict[str, object]:
    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': character},
            },
        }
    )
    response = next(message for message in messages if message.get('id') == request_id)
    return _as_dict(response)


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


def test_language_service_cross_document_navigation(service: LanguageService) -> None:
    service.open_document('file:///defs.tcl', 'proc greet {name} {puts $name}\n', 1)
    service.open_document('file:///use.tcl', 'greet World\n', 1)

    definition_locations = service.definition('file:///use.tcl', 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == 'file:///defs.tcl'
    assert definition_locations[0].span.start.line == 0
    assert definition_locations[0].span.start.character == 5

    hover = service.hover('file:///use.tcl', 0, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)'

    references = service.references('file:///defs.tcl', 0, 5)
    assert {(location.uri, location.span.start.line) for location in references} == {
        ('file:///defs.tcl', 0),
        ('file:///use.tcl', 0),
    }


def test_language_service_hover_includes_proc_comment_blocks(service: LanguageService) -> None:
    service.open_document(
        'file:///defs.tcl',
        '# Greets a user by name.\n# Returns nothing.\nproc greet {name} {puts $name}\n',
        1,
    )
    service.open_document('file:///use.tcl', 'greet World\n', 1)

    hover = service.hover('file:///use.tcl', 0, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'


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
    assert definition_locations[0].span.start.line == 0
    assert definition_locations[0].span.start.character == 4

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
    assert definition_locations[0].span.start.line == 1
    assert definition_locations[0].span.start.character == 13

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
    assert alias_definition_locations[0].span.start.line == 1
    assert alias_definition_locations[0].span.start.character == 13

    alias_hover = service.hover(_MAIN_URI, 4, 18)
    assert alias_hover is not None
    assert alias_hover.contents == 'variable counter'

    namespace_write_definition_locations = service.definition(_MAIN_URI, 2, 38)
    assert len(namespace_write_definition_locations) == 1
    assert namespace_write_definition_locations[0].uri == _MAIN_URI
    assert namespace_write_definition_locations[0].span.start.line == 1
    assert namespace_write_definition_locations[0].span.start.character == 13


def test_language_server_hover_uses_markdown_code_fences_for_signatures(
    server: LanguageServer,
) -> None:
    _open_server_document(
        server,
        '# Greets a user by name.\nproc greet {name} {puts $name}\ngreet World\n',
    )

    hover_value = _hover_markdown_value(server, line=2, character=1)
    assert hover_value == '```tcl\nproc ::greet(name)\n```\n\nGreets a user by name.'


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
            '```tcl\nset {varName args}\n```\n\nRead and write variables.',
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

    qualified_hover = service.hover(main_uri, 2, 3)
    assert qualified_hover is not None
    assert qualified_hover.contents.startswith('builtin command tcltest::cleanupTests')


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
    assert definition_locations[0].span.start.line == 0
    assert definition_locations[0].span.start.character == 5


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
    assert hover_value.startswith(
        '```tcl\nmeta {subcommand args}\n```\n\nMetadata command format for tcl-ls.'
    )
    assert 'structured documentation instead of executable behavior' in hover_value.replace(
        '\n', ' '
    )
    assert 'option name value' in hover_value


def test_language_server_process_message_publishes_diagnostics(server: LanguageServer) -> None:
    messages = server.process_message(
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
        }
    )

    assert len(messages) == 1
    publish = cast(dict[str, object], messages[0])
    assert publish['method'] == 'textDocument/publishDiagnostics'
    params = _as_dict(publish['params'])
    assert params['uri'] == 'file:///diag.tcl'
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']


def test_language_server_run_stdio_round_trip() -> None:
    input_stream = BytesIO()
    output_stream = BytesIO()
    server = LanguageServer(input_stream=input_stream, output_stream=output_stream)

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
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

    server.run_stdio()

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
