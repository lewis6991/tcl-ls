from __future__ import annotations

import json
from io import BytesIO
from typing import BinaryIO, cast

from pygls.exceptions import JsonRpcException
from pygls.protocol.json_rpc import RPCMessage

from tcl_lsp.lsp import LanguageServer


class _CaptureWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def close(self) -> None:
        self._stream.flush()

    def write(self, data: bytes) -> None:
        self._stream.write(data)
        self._stream.flush()


def process_message(server: LanguageServer, raw_message: object) -> list[dict[str, object]]:
    if not isinstance(raw_message, dict):
        return []

    output_stream = BytesIO()
    server.protocol.set_writer(_CaptureWriter(output_stream))

    try:
        raw_payload = cast(dict[str, object], raw_message)
        message = cast(RPCMessage, server.protocol.structure_message(raw_payload))
        server.protocol.handle_message(message)
    except JsonRpcException:
        return []
    except SystemExit:
        pass

    return _decode_lsp_frames(output_stream.getvalue())


def _decode_lsp_frames(payload: bytes) -> list[dict[str, object]]:
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
        messages.append(cast(dict[str, object], json.loads(message_bytes.decode('utf-8'))))

    return messages
