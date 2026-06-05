from __future__ import annotations

INTERRUPTED_EXIT_CODE = 130


def main() -> int:
    try:
        from tcl_lsp.lsp import server

        server.start_io()
    except KeyboardInterrupt:
        return INTERRUPTED_EXIT_CODE
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
