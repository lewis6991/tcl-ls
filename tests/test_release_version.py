from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / 'scripts' / 'release_version.py'


class ReleaseVersionModule(Protocol):
    PYPROJECT_PATH: Path
    PACKAGE_INIT_PATH: Path
    UV_LOCK_PATH: Path
    VSCODE_PACKAGE_JSON_PATH: Path
    VSCODE_PACKAGE_LOCK_PATH: Path

    def compute_release_version(
        self,
        base_version: str,
        channel: str,
        run_number: int,
    ) -> str: ...

    def stamp_version(self, version: str) -> None: ...


def _load_release_version() -> ReleaseVersionModule:
    spec = importlib.util.spec_from_file_location('release_version', SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(ReleaseVersionModule, module)


release_version = _load_release_version()


def test_compute_release_version() -> None:
    assert release_version.compute_release_version('1.2.3', 'stable', 42) == '1.2.3'
    assert release_version.compute_release_version('1.2.3', 'nightly', 42) == '1.2.4-pre.42'

    with pytest.raises(ValueError, match='nightly builds require a positive run number'):
        release_version.compute_release_version('1.2.3', 'nightly', 0)


def test_stamp_version_updates_release_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pyproject_path = tmp_path / 'pyproject.toml'
    package_init_path = tmp_path / '__init__.py'
    uv_lock_path = tmp_path / 'uv.lock'
    package_json_path = tmp_path / 'package.json'
    package_lock_path = tmp_path / 'package-lock.json'

    pyproject_path.write_text(
        '[project]\nname = "tcl-ls"\nversion = "0.2.0"\n',
        encoding='utf-8',
    )
    package_init_path.write_text(
        "__version__ = '0.2.0'\n",
        encoding='utf-8',
    )
    uv_lock_path.write_text(
        '\n'.join(
            [
                '[[package]]',
                'name = "other"',
                'version = "9.9.9"',
                '',
                '[[package]]',
                'name = "tcl-ls"',
                'version = "0.2.0"',
                '',
            ]
        ),
        encoding='utf-8',
    )
    package_json_path.write_text(
        json.dumps({'version': '0.2.0'}),
        encoding='utf-8',
    )
    package_lock_path.write_text(
        json.dumps({'version': '0.2.0', 'packages': {'': {'version': '0.2.0'}}}),
        encoding='utf-8',
    )

    monkeypatch.setattr(release_version, 'PYPROJECT_PATH', pyproject_path)
    monkeypatch.setattr(release_version, 'PACKAGE_INIT_PATH', package_init_path)
    monkeypatch.setattr(release_version, 'UV_LOCK_PATH', uv_lock_path)
    monkeypatch.setattr(release_version, 'VSCODE_PACKAGE_JSON_PATH', package_json_path)
    monkeypatch.setattr(release_version, 'VSCODE_PACKAGE_LOCK_PATH', package_lock_path)

    release_version.stamp_version('0.2.1-pre.7')

    assert 'version = "0.2.1-pre.7"' in pyproject_path.read_text(encoding='utf-8')
    assert package_init_path.read_text(encoding='utf-8') == "__version__ = '0.2.1-pre.7'\n"

    uv_lock_text = uv_lock_path.read_text(encoding='utf-8')
    assert 'name = "other"\nversion = "9.9.9"' in uv_lock_text
    assert 'name = "tcl-ls"\nversion = "0.2.1-pre.7"' in uv_lock_text

    assert json.loads(package_json_path.read_text(encoding='utf-8'))['version'] == '0.2.1-pre.7'
    package_lock = json.loads(package_lock_path.read_text(encoding='utf-8'))
    assert package_lock['version'] == '0.2.1-pre.7'
    assert package_lock['packages']['']['version'] == '0.2.1-pre.7'
