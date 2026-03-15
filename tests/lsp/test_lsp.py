from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import cast

from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.lsp import LanguageServer, LanguageService


def test_language_service_cross_document_navigation() -> None:
    service = LanguageService()
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


def test_language_service_hover_includes_proc_comment_blocks() -> None:
    service = LanguageService()
    service.open_document(
        'file:///defs.tcl',
        '# Greets a user by name.\n# Returns nothing.\nproc greet {name} {puts $name}\n',
        1,
    )
    service.open_document('file:///use.tcl', 'greet World\n', 1)

    hover = service.hover('file:///use.tcl', 0, 1)
    assert hover is not None
    assert hover.contents == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'


def test_language_service_definition_resolves_builtin_command_metadata() -> None:
    service = LanguageService()
    service.open_document('file:///main.tcl', 'set value 1\n', 1)

    builtin = builtin_command('set')
    assert builtin is not None

    definition_locations = service.definition('file:///main.tcl', 0, 1)
    assert len(definition_locations) == 1
    assert definition_locations[0] == builtin.overloads[0].location


def test_language_service_definition_returns_all_builtin_overloads() -> None:
    service = LanguageService()
    service.open_document('file:///main.tcl', 'after 100\n', 1)

    builtin = builtin_command('after')
    assert builtin is not None

    definition_locations = service.definition('file:///main.tcl', 0, 1)
    assert definition_locations == tuple(overload.location for overload in builtin.overloads)


def test_language_server_hover_uses_markdown_code_fences_for_signatures() -> None:
    server = LanguageServer()
    server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': '# Greets a user by name.\nproc greet {name} {puts $name}\ngreet World\n',
                }
            },
        }
    )

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 2, 'character': 1},
            },
        }
    )

    hover_response = next(message for message in messages if message.get('id') == 1)
    hover_response_dict = cast(dict[str, object], hover_response)
    hover_result = _as_dict(hover_response_dict['result'])
    hover_contents = _as_dict(hover_result['contents'])
    assert hover_contents['kind'] == 'markdown'
    assert (
        hover_contents['value']
        == '```tcl\nproc ::greet(name)\n```\n\nGreets a user by name.'
    )


def test_language_server_hover_formats_builtin_command_documentation() -> None:
    server = LanguageServer()
    server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'pwd\n',
                }
            },
        }
    )

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 0, 'character': 1},
            },
        }
    )

    hover_response = next(message for message in messages if message.get('id') == 1)
    hover_response_dict = cast(dict[str, object], hover_response)
    hover_result = _as_dict(hover_response_dict['result'])
    hover_contents = _as_dict(hover_result['contents'])
    assert hover_contents['kind'] == 'markdown'
    hover_value = cast(str, hover_contents['value'])
    assert hover_value.startswith(
        '```tcl\npwd\n```\n\nReturn the absolute path of the current working directory.'
    )
    assert 'Returns the absolute path name of the current working directory.' in hover_value


def test_language_server_hover_includes_single_builtin_signature_when_available() -> None:
    server = LanguageServer()
    server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'set value 1\n',
                }
            },
        }
    )

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 0, 'character': 1},
            },
        }
    )

    hover_response = next(message for message in messages if message.get('id') == 1)
    hover_response_dict = cast(dict[str, object], hover_response)
    hover_result = _as_dict(hover_response_dict['result'])
    hover_contents = _as_dict(hover_result['contents'])
    hover_value = cast(str, hover_contents['value'])
    assert hover_value.startswith('```tcl\nset {varName args}\n```\n\nRead and write variables.')
    assert 'With one argument, return the current value of varName.' in hover_value


def test_language_server_hover_formats_builtin_overloads() -> None:
    server = LanguageServer()
    server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'after 100\n',
                }
            },
        }
    )

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 0, 'character': 1},
            },
        }
    )

    hover_response = next(message for message in messages if message.get('id') == 1)
    hover_response_dict = cast(dict[str, object], hover_response)
    hover_result = _as_dict(hover_response_dict['result'])
    hover_contents = _as_dict(hover_result['contents'])
    hover_value = cast(str, hover_contents['value'])

    assert hover_value.startswith('```tcl\nafter\n```\n\n')
    assert '`after {ms}`\nExecute a command after a time delay' in hover_value
    assert '`after {info {id {}}}`\nReturn information about scheduled after handlers' in hover_value


def test_language_service_infers_packages_from_pkgindex(tmp_path: Path) -> None:
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

    service = LanguageService()
    main_uri = (app_dir / 'main.tcl').as_uri()
    diagnostics = service.open_document(main_uri, 'package require helper\nhelper::greet\n', 1)

    assert diagnostics == ()

    definition_locations = service.definition(main_uri, 1, 2)
    assert len(definition_locations) == 1
    assert definition_locations[0].uri == (helper_dir / 'helper.tcl').as_uri()

    hover = service.hover(main_uri, 1, 2)
    assert hover is not None
    assert hover.contents == 'proc ::helper::greet()'


def test_language_service_analyzes_catch_bodies_and_result_variables() -> None:
    service = LanguageService()
    diagnostics = service.open_document(
        'file:///main.tcl',
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


def test_language_service_reports_unresolved_packages(tmp_path: Path) -> None:
    service = LanguageService()
    main_uri = (tmp_path / 'missing.tcl').as_uri()

    diagnostics = service.open_document(main_uri, 'package require missing\nmissing::run\n', 1)

    assert [diagnostic.code for diagnostic in diagnostics] == ['unresolved-package']


def test_language_service_does_not_report_meta_guard_commands_as_unresolved() -> None:
    service = LanguageService()

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


def test_language_server_hover_formats_meta_builtin_command() -> None:
    server = LanguageServer()
    server.process_message(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///main.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'meta command after {ms}\n',
                }
            },
        }
    )

    messages = server.process_message(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': 'file:///main.tcl'},
                'position': {'line': 0, 'character': 1},
            },
        }
    )

    hover_response = next(message for message in messages if message.get('id') == 1)
    hover_response_dict = cast(dict[str, object], hover_response)
    hover_result = _as_dict(hover_response_dict['result'])
    hover_contents = _as_dict(hover_result['contents'])
    hover_value = cast(str, hover_contents['value'])
    assert hover_value.startswith(
        '```tcl\nmeta {kind name signature}\n```\n\nDeclare metadata for Tcl language entities.'
    )
    assert 'structured documentation instead of executable behavior' in hover_value.replace(
        '\n', ' '
    )


def test_language_server_process_message_publishes_diagnostics() -> None:
    server = LanguageServer()

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
                    'uri': 'file:///main.tcl',
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
                'textDocument': {'uri': 'file:///main.tcl'},
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
    assert definition_results[0]['uri'] == 'file:///main.tcl'
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
