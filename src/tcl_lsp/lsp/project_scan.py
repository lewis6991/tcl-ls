from __future__ import annotations

import logging
import threading
from collections.abc import Callable

type ScanProject = Callable[[Callable[[], bool]], None]


class ProjectScanWorker:
    """Coalesce project scans without holding up document requests."""

    def __init__(self, scan: ScanProject, *, debounce_seconds: float = 0.15) -> None:
        self._scan = scan
        self._debounce_seconds = debounce_seconds
        self._condition = threading.Condition()
        self._version = 0
        self._pending = False
        self._running = False
        self._stopped = False
        self._thread: threading.Thread | None = None

    def schedule(self) -> None:
        with self._condition:
            if self._stopped:
                return
            self._version += 1
            self._pending = True
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name='tcl-ls-project-scan', daemon=True
                )
                self._thread.start()
            self._condition.notify_all()

    def invalidate(self) -> None:
        with self._condition:
            self._version += 1
            self._pending = False
            self._condition.notify_all()

    def wait(self, timeout: float) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending and not self._running, timeout=timeout
            )

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._pending = False
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=1)

    def _stale(self, version: int) -> bool:
        with self._condition:
            return self._stopped or version != self._version

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._stopped)
                if self._stopped:
                    return
                version = self._version
                while True:
                    self._condition.wait(timeout=self._debounce_seconds)
                    if self._stopped:
                        return
                    if version == self._version:
                        break
                    version = self._version
                if not self._pending:
                    continue
                self._pending = False
                self._running = True
            try:
                self._scan(lambda version=version: self._stale(version))
            except Exception:
                logging.getLogger(__name__).exception('Project scan failed')
            finally:
                with self._condition:
                    self._running = False
                    self._condition.notify_all()
