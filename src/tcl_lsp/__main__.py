from __future__ import annotations

import gc

INTERRUPTED_EXIT_CODE = 130


def main() -> int:
    thresholds = gc.get_threshold()
    # Analysis builds many long-lived syntax objects. The default allocation
    # threshold repeatedly scans that growing graph during a workspace build.
    # Keep automatic collection, but allow larger batches in the server process.
    if 0 < thresholds[0] < 50_000:
        gc.set_threshold(50_000, thresholds[1], thresholds[2])

    try:
        from tcl_lsp.lsp import server

        server.start_io()
    except KeyboardInterrupt:
        return INTERRUPTED_EXIT_CODE
    finally:
        gc.set_threshold(*thresholds)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
