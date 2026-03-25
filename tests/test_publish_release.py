from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / 'scripts' / 'publish_release.py'


class PublishReleaseModule(Protocol):
    def main(self, argv: Sequence[str] | None = None) -> int: ...

    def run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


def _load_publish_release() -> PublishReleaseModule:
    spec = importlib.util.spec_from_file_location('publish_release', SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(PublishReleaseModule, module)


publish_release = _load_publish_release()


def _write_assets(assets_dir: Path) -> list[Path]:
    nested_dir = assets_dir / 'nested'
    nested_dir.mkdir(parents=True)
    asset_paths = [
        nested_dir / 'beta.txt',
        assets_dir / 'alpha.txt',
    ]
    for index, asset_path in enumerate(asset_paths, start=1):
        asset_path.write_text(f'asset {index}\n', encoding='utf-8')
    return [assets_dir / 'alpha.txt', nested_dir / 'beta.txt']


def test_main_rejects_missing_assets_directory(tmp_path: Path) -> None:
    missing_assets_dir = tmp_path / 'missing'

    with pytest.raises(ValueError, match='assets directory does not exist'):
        publish_release.main(
            [
                '--assets-dir',
                str(missing_assets_dir),
                '--release-channel',
                'stable',
                '--release-tag',
                'v1.2.3',
                '--release-version',
                '1.2.3',
            ]
        )


def test_main_rejects_empty_assets_directory(tmp_path: Path) -> None:
    assets_dir = tmp_path / 'assets'
    assets_dir.mkdir()

    with pytest.raises(ValueError, match='no release assets found'):
        publish_release.main(
            [
                '--assets-dir',
                str(assets_dir),
                '--release-channel',
                'stable',
                '--release-tag',
                'v1.2.3',
                '--release-version',
                '1.2.3',
            ]
        )


def test_main_uploads_existing_release_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets_dir = tmp_path / 'assets'
    expected_assets = _write_assets(assets_dir)
    commands: list[list[str]] = []

    def fake_run(
        command: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        return subprocess.CompletedProcess(list(command), 0, stdout='')

    monkeypatch.setattr(publish_release, 'run', fake_run)

    result = publish_release.main(
        [
            '--assets-dir',
            str(assets_dir),
            '--release-channel',
            'stable',
            '--release-tag',
            'v1.2.3',
            '--release-version',
            '1.2.3',
        ]
    )

    assert result == 0
    assert commands == [
        ['gh', 'release', 'upload', 'v1.2.3', *(str(path) for path in expected_assets), '--clobber']
    ]


def test_main_creates_nightly_release_before_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets_dir = tmp_path / 'assets'
    expected_assets = _write_assets(assets_dir)
    commands: list[list[str]] = []

    def fake_run(
        command: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        command_list = list(command)
        if command_list == ['git', 'rev-parse', 'HEAD']:
            return subprocess.CompletedProcess(command_list, 0, stdout='abc123\n')
        if command_list == ['gh', 'release', 'view', 'nightly']:
            return subprocess.CompletedProcess(command_list, 1, stdout='')
        return subprocess.CompletedProcess(command_list, 0, stdout='')

    monkeypatch.setattr(publish_release, 'run', fake_run)

    result = publish_release.main(
        [
            '--assets-dir',
            str(assets_dir),
            '--release-channel',
            'nightly',
            '--release-tag',
            'nightly',
            '--release-version',
            'nightly',
            '--create-release',
        ]
    )

    assert result == 0
    assert commands == [
        ['git', 'rev-parse', 'HEAD'],
        ['git', 'tag', '-f', 'nightly', 'abc123'],
        ['git', 'push', 'origin', 'refs/tags/nightly', '--force'],
        ['gh', 'release', 'view', 'nightly'],
        [
            'gh',
            'release',
            'create',
            'nightly',
            '--title',
            'tcl-ls nightly',
            '--prerelease',
            '--generate-notes',
            '--latest=false',
        ],
        [
            'gh',
            'release',
            'upload',
            'nightly',
            *(str(path) for path in expected_assets),
            '--clobber',
        ],
    ]


def test_main_edits_existing_stable_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assets_dir = tmp_path / 'assets'
    expected_assets = _write_assets(assets_dir)
    commands: list[list[str]] = []

    def fake_run(
        command: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        command_list = list(command)
        if command_list == ['git', 'rev-parse', 'HEAD']:
            return subprocess.CompletedProcess(command_list, 0, stdout='abc123\n')
        if command_list == ['gh', 'release', 'view', 'v1.2.3']:
            return subprocess.CompletedProcess(command_list, 0, stdout='release\n')
        return subprocess.CompletedProcess(command_list, 0, stdout='')

    monkeypatch.setattr(publish_release, 'run', fake_run)

    result = publish_release.main(
        [
            '--assets-dir',
            str(assets_dir),
            '--release-channel',
            'stable',
            '--release-tag',
            'v1.2.3',
            '--release-version',
            '1.2.3',
            '--create-release',
        ]
    )

    assert result == 0
    assert commands == [
        ['git', 'rev-parse', 'HEAD'],
        ['git', 'tag', '-f', 'v1.2.3', 'abc123'],
        ['git', 'push', 'origin', 'refs/tags/v1.2.3', '--force'],
        ['gh', 'release', 'view', 'v1.2.3'],
        ['gh', 'release', 'edit', 'v1.2.3', '--title', 'tcl-ls 1.2.3'],
        [
            'gh',
            'release',
            'upload',
            'v1.2.3',
            *(str(path) for path in expected_assets),
            '--clobber',
        ],
    ]
