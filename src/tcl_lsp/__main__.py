from __future__ import annotations

from tcl_lsp.lsp import server


def main() -> None:
    server.start_io()
