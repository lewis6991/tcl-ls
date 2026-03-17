from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def bundled_tcl_meta_path() -> Path:
    return _tools_dir() / 'tcl_meta.tcl'


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='tcl-meta',
        description='Helpers for generating tool metadata for tcl-ls.',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser(
        'helper-path',
        help='Print the bundled Tcl helper path for use with `source` inside a tool Tcl shell.',
    )

    build_file_parser = subparsers.add_parser(
        'build-file',
        help='Build a `.meta.tcl` metadata file using the bundled Tcl helper.',
    )
    build_file_parser.add_argument('output', type=Path)

    args = parser.parse_args(argv)

    if args.command == 'helper-path':
        print(bundled_tcl_meta_path().resolve(strict=False))
        return 0
    if args.command == 'build-file':
        return _run_tcl_script(bundled_tcl_meta_path(), ['build-file', str(args.output)])

    parser.error(f'unsupported command: {args.command}')
    return 2


def _run_tcl_script(script_path: Path, args: Sequence[str]) -> int:
    tclsh_path = shutil.which('tclsh')
    if tclsh_path is None:
        print('error: the `tclsh` executable is required for `tcl-meta`.', file=sys.stderr)
        return 1

    try:
        completed = subprocess.run(
            [tclsh_path, str(script_path), *args],
            check=False,
        )
    except OSError as error:
        print(f'error: failed to launch `tclsh`: {error}', file=sys.stderr)
        return 1
    return int(completed.returncode)


def _tools_dir() -> Path:
    return Path(__file__).resolve().parent / 'tools'
