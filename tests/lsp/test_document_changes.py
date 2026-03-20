from __future__ import annotations

import threading

from tcl_lsp.common import Diagnostic
from tcl_lsp.lsp.document_changes import DocumentChangeWorker

_EMPTY_DIAGNOSTICS: tuple[Diagnostic, ...] = ()


def test_document_change_worker_debounces_rapid_changes() -> None:
    apply_calls: list[str] = []
    published: list[tuple[str, tuple[Diagnostic, ...]]] = []
    published_event = threading.Event()

    def apply_change(uri: str, should_cancel: object) -> tuple[Diagnostic, ...]:
        del should_cancel
        apply_calls.append(uri)
        return _EMPTY_DIAGNOSTICS

    def publish_diagnostics(uri: str, diagnostics: tuple[Diagnostic, ...]) -> None:
        published.append((uri, diagnostics))
        published_event.set()

    worker = DocumentChangeWorker(
        apply_change=apply_change,
        current_document_version=lambda uri: None,
        publish_diagnostics=publish_diagnostics,
        debounce_seconds=0.05,
    )
    worker.start()
    try:
        worker.schedule('file:///main.tcl', 1)
        worker.schedule('file:///main.tcl', 2)
        worker.schedule('file:///main.tcl', 3)

        assert published_event.wait(timeout=1.0)

        assert apply_calls == ['file:///main.tcl']
        assert published == [('file:///main.tcl', _EMPTY_DIAGNOSTICS)]
    finally:
        worker.stop()
