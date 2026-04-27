from __future__ import annotations

import threading
import time
from collections.abc import Callable
from io import BytesIO
from typing import cast

from lsprotocol import types
from pygls.protocol.json_rpc import RPCMessage

from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.lsp import LanguageServer
from tests.lsp.helpers import (
    MAIN_URI,
    CaptureWriter,
    NonClosingBytesIO,
    as_dict,
    decode_frames,
    encode_frame,
    fresh_server,
    open_server_document,
    override_change_document,
    override_open_document,
)
from tests.lsp_support import process_message


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
    show_params = as_dict(show_message['params'])
    assert show_params['type'] == 3
    assert show_params['message'] == 'Indexing workspace.'

    log_message = messages[1]
    assert log_message['method'] == 'window/logMessage'
    log_params = as_dict(log_message['params'])
    assert log_params['type'] == 3
    assert log_params['message'] == 'Indexing workspace for file:///diag.tcl.'

    publish = messages[2]
    assert publish['method'] == 'textDocument/publishDiagnostics'
    params = as_dict(publish['params'])
    assert params['uri'] == 'file:///diag.tcl'
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']


def test_language_server_publishes_unreachable_code_as_unnecessary(
    server: LanguageServer,
) -> None:
    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': 'file:///unreachable.tcl',
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'proc run {} {\n    return ok\n    set later 1\n}\n',
                }
            },
        },
    )

    publish = messages[2]
    assert publish['method'] == 'textDocument/publishDiagnostics'
    params = as_dict(publish['params'])
    diagnostics = cast(list[dict[str, object]], params['diagnostics'])

    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unreachable-code']
    assert diagnostics[0]['severity'] == int(types.DiagnosticSeverity.Hint)
    assert diagnostics[0]['tags'] == [int(types.DiagnosticTag.Unnecessary)]

    diagnostic_range = as_dict(diagnostics[0]['range'])
    end = as_dict(diagnostic_range['end'])
    assert end['character'] == 15


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

    open_server_document(server, 'puts ok\n')

    output_stream = NonClosingBytesIO()
    server.protocol.set_writer(CaptureWriter(output_stream))

    service = SlowChangeService()
    override_change_document(server, service.change_document)

    send(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': MAIN_URI, 'version': 2},
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
                'textDocument': {'uri': MAIN_URI, 'version': 3},
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
            for message in decode_frames(output_stream.getvalue())
            if message.get('method') == 'textDocument/publishDiagnostics'
        ]
        if publish_messages:
            break
        time.sleep(0.01)

    assert service.versions == [2, 3]
    assert len(publish_messages) == 1
    params = as_dict(publish_messages[0]['params'])
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
    params = as_dict(log_notification['params'])
    assert params == {'type': 3, 'message': 'tcl-ls started.'}


def test_language_server_process_message_reports_indexing_progress_when_supported() -> None:
    server = fresh_server()
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
    assert as_dict(create_request['params']) == {'token': 'tcl-ls/indexing/1'}

    begin_params = as_dict(messages[1]['params'])
    assert begin_params['token'] == 'tcl-ls/indexing/1'
    begin_value = as_dict(begin_params['value'])
    assert begin_value == {
        'kind': 'begin',
        'title': 'Indexing workspace',
        'message': 'Starting analysis',
        'percentage': 0,
    }

    report_values = [as_dict(as_dict(message['params'])['value']) for message in messages[2:6]]
    assert report_values == [
        {'kind': 'report', 'message': 'Rebuilding workspace index', 'percentage': 10},
        {'kind': 'report', 'message': 'Indexing workspace files (1/1)', 'percentage': 45},
        {'kind': 'report', 'message': 'Loading workspace dependencies', 'percentage': 50},
        {'kind': 'report', 'message': 'Analyzing workspace (1/1)', 'percentage': 95},
    ]

    log_params = as_dict(messages[6]['params'])
    assert log_params == {'type': 3, 'message': 'Indexing workspace for file:///diag.tcl.'}

    diagnostics = cast(list[dict[str, object]], as_dict(messages[7]['params'])['diagnostics'])
    assert [diagnostic['code'] for diagnostic in diagnostics] == ['unresolved-variable']

    end_params = as_dict(messages[8]['params'])
    assert end_params['token'] == 'tcl-ls/indexing/1'
    end_value = as_dict(end_params['value'])
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
    open_server_document(server, 'proc greet {} {return ok}\ngreet\n')

    messages = process_message(
        server,
        {
            'jsonrpc': '2.0',
            'id': 8,
            'method': 'textDocument/rename',
            'params': {
                'textDocument': {'uri': MAIN_URI},
                'position': {'line': 1, 'character': 1},
                'newName': 'welcome',
            },
        },
    )

    assert len(messages) == 1
    response = messages[0]
    assert response['id'] == 8
    result = as_dict(response['result'])
    changes = cast(dict[str, list[dict[str, object]]], result['changes'])
    assert tuple(changes) == (MAIN_URI,)
    assert changes[MAIN_URI] == [
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
    output_stream = NonClosingBytesIO()
    server = fresh_server()

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': MAIN_URI,
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
                'textDocument': {'uri': MAIN_URI},
                'position': {'line': 1, 'character': 1},
            },
        },
        {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown', 'params': {}},
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    server.start_io(input_stream, output_stream)

    messages = decode_frames(output_stream.getvalue())
    initialize_response = next(message for message in messages if message.get('id') == 1)
    initialize_result = as_dict(initialize_response['result'])
    capabilities = as_dict(initialize_result['capabilities'])
    assert capabilities['definitionProvider'] is True

    diagnostics_notification = next(
        message
        for message in messages
        if message.get('method') == 'textDocument/publishDiagnostics'
    )
    diagnostics_params = as_dict(diagnostics_notification['params'])
    assert diagnostics_params['diagnostics'] == []

    definition_response = next(message for message in messages if message.get('id') == 2)
    definition_results = cast(list[dict[str, object]], definition_response['result'])
    definition_range = as_dict(definition_results[0]['range'])
    assert definition_results[0]['uri'] == MAIN_URI
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
    output_stream = NonClosingBytesIO()
    server = fresh_server()
    override_open_document(server, service.open_document)

    frames: list[dict[str, object]] = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'capabilities': {}}},
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {
                    'uri': MAIN_URI,
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    thread = threading.Thread(target=server.start_io, args=(input_stream, output_stream))
    thread.start()

    assert service.started.wait(timeout=1)
    messages = decode_frames(output_stream.getvalue())
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
    output_stream = NonClosingBytesIO()
    server = fresh_server()
    override_open_document(server, service.open_document)

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
                    'uri': MAIN_URI,
                    'languageId': 'tcl',
                    'version': 1,
                    'text': 'puts ok\n',
                }
            },
        },
        {'jsonrpc': '2.0', 'method': 'exit'},
    ]
    input_stream.write(b''.join(encode_frame(frame) for frame in frames))
    input_stream.seek(0)

    thread = threading.Thread(target=server.start_io, args=(input_stream, output_stream))
    thread.start()

    assert service.started.wait(timeout=1)
    progress_messages = [
        message
        for message in decode_frames(output_stream.getvalue())
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
