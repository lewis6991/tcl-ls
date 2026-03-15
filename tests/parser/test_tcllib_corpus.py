from __future__ import annotations

import os
from pathlib import Path

import pytest

from tcl_lsp.parser import Parser

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TCLLIB_DIR = PROJECT_ROOT / '.cache' / 'tcllib'
_TCLLIB_PATTERNS = ('*.tcl', '*.tm', '*.test')


def _tcllib_root() -> Path:
    configured = os.environ.get('TCLLIB_DIR')
    if configured is None:
        return DEFAULT_TCLLIB_DIR
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _read_source(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ('utf-8', 'iso-8859-1'):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise AssertionError(f'Could not decode {path}: {last_error}')


def _tcllib_sources(root: Path) -> list[Path]:
    return sorted({path for pattern in _TCLLIB_PATTERNS for path in root.rglob(pattern)})


def test_parser_parses_tcllib_corpus_without_diagnostics() -> None:
    tcllib_root = _tcllib_root()
    if not tcllib_root.is_dir():
        pytest.skip(f'tcllib checkout not found at {tcllib_root}; run `make tcllib` first')

    sources = _tcllib_sources(tcllib_root)
    assert sources, f'No Tcl sources found under {tcllib_root}'

    parser = Parser()
    failures: list[str] = []
    for path in sources:
        relative_path = path.relative_to(tcllib_root)
        try:
            result = parser.parse_document(str(relative_path), _read_source(path))
        except Exception as exc:
            failures.append(f'{relative_path}: crashed with {exc!r}')
            continue
        if result.diagnostics:
            diagnostics = ', '.join(
                f'{diagnostic.code}@{diagnostic.span.start.line + 1}:{diagnostic.span.start.character + 1}'
                for diagnostic in result.diagnostics
            )
            failures.append(f'{relative_path}: {diagnostics}')

    if failures:
        preview = '\n'.join(failures[:20])
        remaining = len(failures) - min(len(failures), 20)
        suffix = f'\n... and {remaining} more failures' if remaining else ''
        pytest.fail(
            f'Parser reported issues in {len(failures)} of {len(sources)} tcllib files:\n'
            f'{preview}{suffix}'
        )
