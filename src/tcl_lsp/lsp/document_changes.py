from __future__ import annotations

import threading
from collections.abc import Callable

from tcl_lsp.common import Diagnostic

type CancelCallback = Callable[[], bool]
type ApplyDocumentChange = Callable[[str, CancelCallback | None], tuple[Diagnostic, ...] | None]
type CurrentDocumentVersion = Callable[[str], int | None]
type PublishDiagnostics = Callable[[str, tuple[Diagnostic, ...]], None]


class DocumentChangeWorker:
    _apply_change: ApplyDocumentChange
    _condition: threading.Condition
    _current_document_version: CurrentDocumentVersion
    _debounce_seconds: float
    _pending_changes: dict[str, int]
    _publish_diagnostics: PublishDiagnostics
    _request_version: int
    _stop_requested: bool
    _worker: threading.Thread | None

    def __init__(
        self,
        *,
        apply_change: ApplyDocumentChange,
        current_document_version: CurrentDocumentVersion,
        publish_diagnostics: PublishDiagnostics,
        debounce_seconds: float = 0.15,
    ) -> None:
        self._apply_change = apply_change
        self._condition = threading.Condition()
        self._current_document_version = current_document_version
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._pending_changes = {}
        self._publish_diagnostics = publish_diagnostics
        self._request_version = 0
        self._stop_requested = False
        self._worker = None

    def start(self) -> None:
        with self._condition:
            if self._worker is not None and self._worker.is_alive():
                return
            self._pending_changes = {}
            self._request_version = 0
            self._stop_requested = False
            self._worker = threading.Thread(
                target=self._run,
                name='tcl-ls-change-worker',
                daemon=True,
            )
            self._worker.start()

    def stop(self) -> None:
        worker: threading.Thread | None
        with self._condition:
            self._stop_requested = True
            self._pending_changes = {}
            self._condition.notify_all()
            worker = self._worker
            self._worker = None
        if worker is not None and worker.is_alive():
            worker.join(timeout=1)

    def schedule(self, uri: str, version: int) -> None:
        current_version = self._current_document_version(uri)
        with self._condition:
            pending_change = self._pending_changes.get(uri)
            if pending_change is not None and version <= pending_change:
                return
            if current_version is not None and version <= current_version:
                return
            self._pending_changes[uri] = version
            self._request_version += 1
            self._condition.notify()

    def discard(self, uri: str) -> None:
        with self._condition:
            self._pending_changes.pop(uri, None)
            self._request_version += 1
            self._condition.notify_all()

    def invalidate(self) -> None:
        with self._condition:
            self._request_version += 1
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending_changes and not self._stop_requested:
                    self._condition.wait()
                if self._stop_requested:
                    return
                request_version = self._request_version
                if self._debounce_seconds > 0:
                    while True:
                        self._condition.wait(timeout=self._debounce_seconds)
                        if self._stop_requested:
                            return
                        if self._request_version == request_version:
                            break
                        request_version = self._request_version
                pending_changes = tuple(self._pending_changes.items())

            diagnostics_by_uri: dict[str, tuple[Diagnostic, ...]] = {}
            cancelled = False
            for uri, _ in pending_changes:
                diagnostics = self._apply_change(
                    uri,
                    lambda request_version=request_version: self._request_is_stale(request_version),
                )
                if diagnostics is None:
                    cancelled = True
                    break
                diagnostics_by_uri[uri] = diagnostics

            if cancelled or self._request_is_stale(request_version):
                continue

            with self._condition:
                if self._stop_requested or self._request_version != request_version:
                    continue
                for uri, version in pending_changes:
                    current_change = self._pending_changes.get(uri)
                    if current_change is not None and current_change == version:
                        self._pending_changes.pop(uri, None)

            for uri, diagnostics in diagnostics_by_uri.items():
                if self._request_is_stale(request_version):
                    break
                self._publish_diagnostics(uri, diagnostics)

    def _request_is_stale(self, request_version: int) -> bool:
        return self._stop_requested or self._request_version != request_version
