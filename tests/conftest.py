from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tcl_lsp.lsp import LanguageServer, LanguageService  # noqa: E402
from tcl_lsp.parser import Parser  # noqa: E402


@pytest.fixture
def parser() -> Parser:
    return Parser()


@pytest.fixture
def service() -> LanguageService:
    return LanguageService()


@pytest.fixture
def server() -> LanguageServer:
    return LanguageServer()
