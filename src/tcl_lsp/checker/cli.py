from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TextIO

from .reporting import Palette, StreamReporter
from .service import DEFAULT_WORKER_COUNT, check_project

type ColorMode = Literal['auto', 'always', 'never']


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    target = Path(args.path)
    palette = Palette(_color_enabled(args.color, sys.stdout))
    reporter = StreamReporter(
        root=target.expanduser().resolve(strict=False),
        out=sys.stdout,
        err=sys.stderr,
        palette=palette,
        context_lines=args.context_lines,
    )

    try:
        report = check_project(
            target,
            reporter=reporter,
            threads=args.threads,
            plugin_paths=args.plugin_paths,
        )
    except KeyboardInterrupt:
        reporter.abort()
        print('Interrupted.', file=sys.stderr)
        return 130
    except (OSError, ValueError, AssertionError) as exc:
        reporter.abort()
        print(str(exc), file=sys.stderr)
        return 1

    if args.fail_on_diagnostics and report.diagnostics:
        return 1
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='tcl-check',
        description='Analyze Tcl sources under a file or directory and print diagnostics.',
    )
    parser.add_argument('path', help='Tcl source file or project directory to analyze')
    parser.add_argument(
        '--color',
        choices=('auto', 'always', 'never'),
        default='auto',
        help='Colorize output. Defaults to `auto`.',
    )
    parser.add_argument(
        '--context-lines',
        type=_non_negative_int,
        default=0,
        help='Show this many lines of surrounding source context for each diagnostic.',
    )
    parser.add_argument(
        '--fail-on-diagnostics',
        action='store_true',
        help='Exit with status 1 when diagnostics are reported.',
    )
    parser.add_argument(
        '-j',
        '--threads',
        type=_worker_count,
        default=DEFAULT_WORKER_COUNT,
        help=(
            f'Index documents with this many worker processes. Defaults to {DEFAULT_WORKER_COUNT}.'
        ),
    )
    parser.add_argument(
        '--plugin-path',
        action='append',
        dest='plugin_paths',
        default=[],
        help=(
            'Load project metadata from this path. Accepts a metadata directory, '
            'a metadata `.meta.tcl` file, or a Tcl plugin `.tcl` file. When a '
            'plugin script is passed, sibling metadata files are discovered from '
            'its parent directory. Legacy `.tm` plugin scripts are also accepted. '
            'Paths from `tcllsrc.tcl` are loaded automatically.'
        ),
    )
    return parser.parse_args(argv)


def _color_enabled(mode: ColorMode, stream: TextIO) -> bool:
    if mode == 'always':
        return True
    if mode == 'never':
        return False
    return stream.isatty() and 'NO_COLOR' not in os.environ


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError('value must be >= 0')
    return parsed


def _worker_count(value: str | int) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('value must be >= 1')
    return parsed
