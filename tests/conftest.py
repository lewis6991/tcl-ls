from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tcl_lsp.lsp import LanguageServer  # noqa: E402
from tcl_lsp.lsp import server as lsp_server  # noqa: E402
from tcl_lsp.parser import Parser  # noqa: E402
from tests.lsp_service import LanguageService  # noqa: E402
from tests.lsp_support import process_message  # noqa: E402


@pytest.fixture
def parser() -> Parser:
    return Parser()


@pytest.fixture
def service() -> LanguageService:
    return LanguageService()


@pytest.fixture
def server() -> Iterator[LanguageServer]:
    lsp_server.reset()
    process_message(
        lsp_server,
        {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'capabilities': {}}},
    )
    yield lsp_server
    lsp_server.reset()
