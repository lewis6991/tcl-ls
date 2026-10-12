"""Replay a small edit against a real project, with optional CPU profiling."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

from lsprotocol import types

from tcl_lsp.lsp import LanguageServer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--replace', nargs=2, required=True, metavar=('OLD', 'NEW'))
    parser.add_argument('--edits', type=int, default=5)
    parser.add_argument('--profile', type=Path, help='write cProfile data instead of pure timings')
    args = parser.parse_args()
    if args.edits < 1:
        parser.error('--edits must be positive')
    source = args.source.resolve()
    original = source.read_text(encoding='utf-8')
    old, new = args.replace
    if not old or old not in original or old == new:
        parser.error('OLD must occur in the file and differ from NEW')
    modified = original.replace(old, new, 1)
    offset = original.index(old)
    line = original[:offset].count('\n')
    character = offset - original.rfind('\n', 0, offset) - 1
    uri = source.as_uri()
    print(json.dumps({'source': str(source), 'profiled': args.profile is not None}), flush=True)

    def measure[T](operation: str, action: Callable[[], T]) -> T:
        started = time.perf_counter()
        result = action()
        elapsed = time.perf_counter() - started
        payload = result.data if isinstance(result, types.SemanticTokens) else result
        print(
            json.dumps(
                {
                    'operation': operation,
                    'seconds': elapsed,
                    'result_hash': hashlib.sha256(repr(payload).encode()).hexdigest(),
                }
            ),
            flush=True,
        )
        return result

    server = LanguageServer()
    # Initialize the protocol workspace without a transport.
    list(
        server.protocol.lsp_initialize(
            types.InitializeParams(
                capabilities=types.ClientCapabilities(), root_uri=source.parent.as_uri()
            )
        )
    )

    def buffer(text: str, version: int) -> None:
        server.workspace.put_text_document(
            types.TextDocumentItem(uri=uri, language_id='tcl', version=version, text=text)
        )

    def completion() -> object:
        return server.completion_items_at(
            server.analysis_snapshot(), uri=uri, line=line, character=character
        )

    profiler = cProfile.Profile() if args.profile is not None else None
    try:
        if profiler is not None:
            profiler.enable()
        buffer(original, 1)
        measure('open', lambda: server.open_document(uri, original, 1))
        measure('tokens', lambda: server.semantic_tokens(uri))
        measure('completion', completion)

        buffer(modified, 2)
        measure('pending_completion', completion)
        for version in range(2, args.edits + 2):
            text = modified if version % 2 == 0 else original
            buffer(text, version)
            measure('edit', partial(server.change_document, uri, text, version))
            measure('tokens', lambda: server.semantic_tokens(uri))
            measure('completion', completion)
    finally:
        if profiler is not None:
            profiler.disable()
            profiler.dump_stats(args.profile)
        server.shutdown()


if __name__ == '__main__':
    main()
