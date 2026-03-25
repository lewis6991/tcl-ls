from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, cast

from tcl_lsp.lsp import server as lsp_server


def test_main_module_starts_io_when_executed_as_script() -> None:
    start_io_calls = 0

    def fake_start_io() -> None:
        nonlocal start_io_calls
        start_io_calls += 1

    main_path = Path(__file__).resolve().parents[1] / 'src' / 'tcl_lsp' / '__main__.py'
    original_start_io = lsp_server.start_io
    cast(Any, lsp_server).start_io = fake_start_io
    try:
        runpy.run_path(str(main_path), run_name='__main__')
    finally:
        cast(Any, lsp_server).start_io = original_start_io

    assert start_io_calls == 1
