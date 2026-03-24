"""Archive release assets with consistent layout across local and CI builds.

This helper exists so the top-level make targets and the cross-platform
release workflow produce the same archive contents and root directory shape on
Linux, macOS, and Windows.
"""

from __future__ import annotations

import argparse
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Archive a built release asset directory.')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root-name', required=True)
    parser.add_argument('--include', type=Path, action='append', default=[])
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f'source must be a directory: {source}')

    output = args.output.resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary_directory:
        staging_root = Path(temporary_directory) / args.root_name

        # Stage files
        shutil.copytree(source, staging_root)
        for include_path in args.include:
            include_source = include_path.resolve(strict=True)
            include_destination = staging_root / include_path.name
            if include_source.is_dir():
                shutil.copytree(include_source, include_destination)
            else:
                include_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(include_source, include_destination)

        # Write archive
        if output.suffixes[-2:] == ['.tar', '.gz']:
            with tarfile.open(output, 'w:gz') as archive:
                archive.add(staging_root, arcname=staging_root.name)
        elif output.suffix == '.zip':
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging_root.rglob('*')):
                    archive.write(path, path.relative_to(staging_root.parent))
        else:
            raise ValueError(f'unsupported archive format: {output}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
