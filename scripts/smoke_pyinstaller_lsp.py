from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
from collections.abc import Callable
from io import BufferedReader
from pathlib import Path
from typing import cast

_INITIALIZE_REQUEST_ID = 1
_SHUTDOWN_REQUEST_ID = 2
_RESPONSE_TIMEOUT_SECONDS = 5.0
_SHUTDOWN_TIMEOUT_SECONDS = 2.0

type LspMessage = dict[str, object]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Smoke-test a frozen tcl-ls executable over stdio.'
    )
    parser.add_argument('server', type=Path, help='Path to the frozen tcl-ls executable.')
    args = parser.parse_args(argv)

    server_path = args.server.resolve(strict=True)
    process = subprocess.Popen(
        [str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _write_message(
            process,
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
            process,
            lambda message: message.get('id') == _INITIALIZE_REQUEST_ID,
            timeout=_RESPONSE_TIMEOUT_SECONDS,
        )
        if 'result' not in response:
            raise RuntimeError(f'initialize did not return a result: {response!r}')

        _write_message(
            process,
            {
                'jsonrpc': '2.0',
                'id': _SHUTDOWN_REQUEST_ID,
                'method': 'shutdown',
                'params': None,
            },
        )
        _wait_for_message(
            process,
            lambda message: message.get('id') == _SHUTDOWN_REQUEST_ID,
            timeout=_RESPONSE_TIMEOUT_SECONDS,
        )
        _write_message(
            process,
            {
                'jsonrpc': '2.0',
                'method': 'exit',
                'params': None,
            },
        )
        try:
            return process.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Server did not exit cleanly after shutdown.') from error
    except Exception as error:
        stderr = _drain_stderr(process).decode('utf-8', errors='replace').strip()
        if stderr:
            print(stderr, file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)


def _write_message(process: subprocess.Popen[bytes], message: dict[str, object]) -> None:
    stdin = process.stdin
    if stdin is None:
        raise RuntimeError('Server stdin is unavailable.')

    body = json.dumps(message).encode('utf-8')
    stdin.write(b'Content-Length: ' + str(len(body)).encode('ascii') + b'\r\n\r\n' + body)
    stdin.flush()


def _wait_for_message(
    process: subprocess.Popen[bytes],
    predicate: Callable[[LspMessage], bool],
    *,
    timeout: float,
) -> LspMessage:
    deadline = time.monotonic() + timeout
    while True:
        message = _read_message(process, timeout=max(0.0, deadline - time.monotonic()))
        if predicate(message):
            return message


def _read_message(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> LspMessage:
    if timeout <= 0:
        raise TimeoutError('Timed out waiting for LSP output.')

    stdout = process.stdout
    if stdout is None:
        raise RuntimeError('Server stdout is unavailable.')

    buffer = bytearray()
    deadline = time.monotonic() + timeout

    while b'\r\n\r\n' not in buffer:
        buffer.extend(_read_chunk(process, cast(BufferedReader, stdout), deadline))

    header_end = buffer.index(b'\r\n\r\n')
    header_block = bytes(buffer[:header_end]).decode('ascii')
    body = bytearray(buffer[header_end + 4 :])
    content_length = _parse_content_length(header_block)

    while len(body) < content_length:
        body.extend(_read_chunk(process, cast(BufferedReader, stdout), deadline))

    message_bytes = bytes(body[:content_length])
    return cast(LspMessage, json.loads(message_bytes.decode('utf-8')))


def _parse_content_length(header_block: str) -> int:
    for header_line in header_block.split('\r\n'):
        if header_line.lower().startswith('content-length:'):
            return int(header_line.split(':', maxsplit=1)[1].strip())
    raise RuntimeError(f'Missing Content-Length header: {header_block!r}')


def _read_chunk(
    process: subprocess.Popen[bytes],
    stream: BufferedReader,
    deadline: float,
) -> bytes:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Timed out waiting for LSP output.')

        ready, _, _ = select.select([stream], [], [], remaining)
        if ready:
            chunk = stream.read1(65536)
            if chunk:
                return chunk

            returncode = process.poll()
            if returncode is None:
                continue

            stderr = _drain_stderr(process).decode('utf-8', errors='replace').strip()
            if stderr:
                raise RuntimeError(
                    f'Server exited with code {returncode} before responding:\n{stderr}'
                )
            raise RuntimeError(f'Server exited with code {returncode} before responding.')

        returncode = process.poll()
        if returncode is not None:
            stderr = _drain_stderr(process).decode('utf-8', errors='replace').strip()
            if stderr:
                raise RuntimeError(f'Server exited with code {returncode}:\n{stderr}')
            raise RuntimeError(f'Server exited with code {returncode}.')


def _drain_stderr(process: subprocess.Popen[bytes]) -> bytes:
    stderr = process.stderr
    if stderr is None:
        return b''

    chunks: list[bytes] = []
    while True:
        ready, _, _ = select.select([cast(BufferedReader, stderr)], [], [], 0)
        if not ready:
            break

        chunk = cast(BufferedReader, stderr).read1(65536)
        if not chunk:
            break
        chunks.append(chunk)

    return b''.join(chunks)


if __name__ == '__main__':
    raise SystemExit(main())
