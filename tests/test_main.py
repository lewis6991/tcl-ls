from __future__ import annotations

import runpy
import sys
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from tcl_lsp import __main__ as tcl_ls_main


def _install_fake_lsp(
    monkeypatch: pytest.MonkeyPatch,
    start_io: Callable[[], None],
) -> None:
    lsp_module = types.ModuleType('tcl_lsp.lsp')
    lsp_module.__dict__['server'] = types.SimpleNamespace(start_io=start_io)
    monkeypatch.setitem(sys.modules, 'tcl_lsp.lsp', lsp_module)


def test_main_module_starts_io_when_executed_as_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_io_calls = 0

    def fake_start_io() -> None:
        nonlocal start_io_calls
        start_io_calls += 1

    _install_fake_lsp(monkeypatch, fake_start_io)

    main_path = Path(__file__).resolve().parents[1] / 'src' / 'tcl_lsp' / '__main__.py'
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(main_path), run_name='__main__')

    assert start_io_calls == 1
    assert exit_info.value.code == 0


def test_main_module_handles_keyboard_interrupt_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_start_io() -> None:
        raise KeyboardInterrupt

    _install_fake_lsp(monkeypatch, fake_start_io)

    exit_code = tcl_ls_main.main()
    captured = capsys.readouterr()

    assert exit_code == 130
    assert captured.out == ''
    assert captured.err == ''
