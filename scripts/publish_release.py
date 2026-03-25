"""Create or update GitHub releases and upload built assets.

This keeps the GitHub Actions workflow thin while preserving the two current
release modes:
- stable uploads assets to the release already created by release-please
- nightly refreshes a rolling prerelease before uploading new assets
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Create or update a GitHub release and upload built assets.'
    )
    parser.add_argument('--assets-dir', type=Path, required=True)
    parser.add_argument('--release-channel', required=True)
    parser.add_argument('--release-tag', required=True)
    parser.add_argument('--release-version', required=True)
    parser.add_argument('--create-release', action='store_true')
    args = parser.parse_args(argv)

    if args.create_release:
        create_or_update_release(
            args.release_channel,
            args.release_tag,
            args.release_version,
        )

    if not args.assets_dir.is_dir():
        raise ValueError(f'assets directory does not exist: {args.assets_dir}')

    assets = sorted(str(path) for path in args.assets_dir.rglob('*') if path.is_file())
    if not assets:
        raise ValueError(f'no release assets found in {args.assets_dir}')

    run(['gh', 'release', 'upload', args.release_tag, *assets, '--clobber'])
    return 0


def create_or_update_release(
    release_channel: str,
    release_tag: str,
    release_version: str,
) -> None:
    prerelease = release_channel != 'stable'
    release_commit = run(['git', 'rev-parse', 'HEAD'], capture_output=True).stdout.strip()
    run(['git', 'tag', '-f', release_tag, release_commit])
    run(['git', 'push', 'origin', f'refs/tags/{release_tag}', '--force'])

    release_args = ['--title', f'tcl-ls {release_version}']
    if prerelease:
        release_args.append('--prerelease')

    if run(['gh', 'release', 'view', release_tag], check=False).returncode == 0:
        run(['gh', 'release', 'edit', release_tag, *release_args])
        return

    create_args = ['gh', 'release', 'create', release_tag, *release_args, '--generate-notes']
    if prerelease:
        create_args.append('--latest=false')
    run(create_args)


def run(
    command: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=check,
        capture_output=capture_output,
        text=True,
    )


if __name__ == '__main__':
    raise SystemExit(main())
