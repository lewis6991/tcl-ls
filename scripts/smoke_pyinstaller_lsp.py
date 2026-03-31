from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BufferedReader
from pathlib import Path
from typing import cast

_INITIALIZE_REQUEST_ID = 1
_SHUTDOWN_REQUEST_ID = 2
_RESPONSE_TIMEOUT_SECONDS = 5.0
_SHUTDOWN_TIMEOUT_SECONDS = 2.0

type LspMessage = dict[str, object]
type StreamQueueItem = bytes | object

_STREAM_EOF = object()


@dataclass(slots=True)
class _SmokeSession:
    process: subprocess.Popen[bytes]
    stdout_queue: queue.Queue[StreamQueueItem]
    stderr_queue: queue.Queue[StreamQueueItem]
    stdout_buffer: bytearray = field(default_factory=bytearray)
    stderr_chunks: list[bytes] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Smoke-test a frozen tcl-ls executable over stdio.'
    )
    parser.add_argument('server', type=Path, help='Path to the frozen tcl-ls executable.')
    args = parser.parse_args(argv)

    server_path = args.server.resolve(strict=True)
    session = _start_session(server_path)

    try:
        _write_message(
            session.process,
            {
                'jsonrpc': '2.0',
                'id': _INITIALIZE_REQUEST_ID,
                'method': 'initialize',
                'params': {
                    'processId': None,
                    'rootUri': None,
                    'capabilities': {},
                    'workspaceFolders': None,
                },
            },
        )
        response = _wait_for_message(
            session,
            lambda message: message.get('id') == _INITIALIZE_REQUEST_ID,
            timeout=_RESPONSE_TIMEOUT_SECONDS,
        )
        if 'result' not in response:
            raise RuntimeError(f'initialize did not return a result: {response!r}')

        _write_message(
            session.process,
            {
                'jsonrpc': '2.0',
                'id': _SHUTDOWN_REQUEST_ID,
                'method': 'shutdown',
                'params': None,
            },
        )
        _wait_for_message(
            session,
            lambda message: message.get('id') == _SHUTDOWN_REQUEST_ID,
            timeout=_RESPONSE_TIMEOUT_SECONDS,
        )
        _write_message(
            session.process,
            {
                'jsonrpc': '2.0',
                'method': 'exit',
                'params': None,
            },
        )
        try:
            return session.process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Server did not exit cleanly after shutdown.') from error
    except Exception as error:
        stderr = _stderr_text(session)
        if stderr:
            print(stderr, file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=1.0)


def _write_message(process: subprocess.Popen[bytes], message: dict[str, object]) -> None:
    stdin = process.stdin
    if stdin is None:
        raise RuntimeError('Server stdin is unavailable.')

    body = json.dumps(message).encode('utf-8')
    stdin.write(b'Content-Length: ' + str(len(body)).encode('ascii') + b'\r\n\r\n' + body)
    stdin.flush()


def _wait_for_message(
    session: _SmokeSession,
    predicate: Callable[[LspMessage], bool],
    *,
    timeout: float,
) -> LspMessage:
    deadline = time.monotonic() + timeout
    while True:
        message = _read_message(session, timeout=max(0.0, deadline - time.monotonic()))
        if predicate(message):
            return message


def _read_message(
    session: _SmokeSession,
    *,
    timeout: float,
) -> LspMessage:
    if timeout <= 0:
        raise TimeoutError('Timed out waiting for LSP output.')

    deadline = time.monotonic() + timeout

    while b'\r\n\r\n' not in session.stdout_buffer:
        session.stdout_buffer.extend(_read_chunk(session, deadline))

    header_end = session.stdout_buffer.index(b'\r\n\r\n')
    header_block = bytes(session.stdout_buffer[:header_end]).decode('ascii')
    body_start = header_end + 4
    content_length = _parse_content_length(header_block)

    while len(session.stdout_buffer) - body_start < content_length:
        session.stdout_buffer.extend(_read_chunk(session, deadline))

    message_end = body_start + content_length
    message_bytes = bytes(session.stdout_buffer[body_start:message_end])
    del session.stdout_buffer[:message_end]
    return cast(LspMessage, json.loads(message_bytes.decode('utf-8')))


def _parse_content_length(header_block: str) -> int:
    for header_line in header_block.split('\r\n'):
        if header_line.lower().startswith('content-length:'):
            return int(header_line.split(':', maxsplit=1)[1].strip())
    raise RuntimeError(f'Missing Content-Length header: {header_block!r}')


def _read_chunk(session: _SmokeSession, deadline: float) -> bytes:
    while True:
        _drain_stderr(session)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Timed out waiting for LSP output.')

        try:
            item = session.stdout_queue.get(timeout=remaining)
        except queue.Empty as error:
            if session.process.poll() is not None:
                raise _process_exit_error(session, before_responding=False) from error
            continue

        if item is _STREAM_EOF:
            raise _process_exit_error(session, before_responding=True)
        return cast(bytes, item)


def _start_session(server_path: Path) -> _SmokeSession:
    process = subprocess.Popen(
        [str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:
        raise RuntimeError('Server pipes are unavailable.')

    stdout_queue: queue.Queue[StreamQueueItem] = queue.Queue()
    stderr_queue: queue.Queue[StreamQueueItem] = queue.Queue()
    _start_reader_thread(cast(BufferedReader, stdout), stdout_queue, name='stdout')
    _start_reader_thread(cast(BufferedReader, stderr), stderr_queue, name='stderr')
    return _SmokeSession(
        process=process,
        stdout_queue=stdout_queue,
        stderr_queue=stderr_queue,
    )


def _start_reader_thread(
    stream: BufferedReader,
    output_queue: queue.Queue[StreamQueueItem],
    *,
    name: str,
) -> None:
    thread = threading.Thread(
        target=_reader,
        args=(stream, output_queue),
        daemon=True,
        name=f'smoke-{name}',
    )
    thread.start()


def _reader(stream: BufferedReader, output_queue: queue.Queue[StreamQueueItem]) -> None:
    while True:
        chunk = stream.read1(65536)
        if not chunk:
            output_queue.put(_STREAM_EOF)
            return
        output_queue.put(chunk)


def _drain_stderr(session: _SmokeSession) -> None:
    while True:
        try:
            item = session.stderr_queue.get_nowait()
        except queue.Empty:
            return

        if item is _STREAM_EOF:
            return
        session.stderr_chunks.append(cast(bytes, item))


def _stderr_text(session: _SmokeSession) -> str:
    _drain_stderr(session)
    if not session.stderr_chunks:
        return ''
    return b''.join(session.stderr_chunks).decode('utf-8', errors='replace').strip()


def _process_exit_error(session: _SmokeSession, *, before_responding: bool) -> RuntimeError:
    returncode = session.process.poll()
    stderr_text = _stderr_text(session)
    context = ' before responding' if before_responding else ''
    if returncode is None:
        message = f'Server stopped unexpectedly{context}.'
    else:
        message = f'Server exited with code {returncode}{context}.'
    if stderr_text:
        message = f'{message}\n{stderr_text}'
    return RuntimeError(message)


if __name__ == '__main__':
    raise SystemExit(main())
