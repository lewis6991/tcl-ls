from __future__ import annotations

from tcl_lsp.lsp import LanguageServer


def main() -> None:
    LanguageServer().run_stdio()
