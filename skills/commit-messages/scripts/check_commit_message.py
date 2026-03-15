#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SUBJECT_LIMIT = 50
_BODY_LIMIT = 72
_ALLOWED_TYPES = ('feat', 'fix', 'perf', 'docs', 'refactor', 'test', 'chore', 'ci')


def validate_message(message: str) -> tuple[str, ...]:
    lines = message.splitlines()
    errors: list[str] = []
    if not lines:
        return ('commit message is empty',)

    subject = lines[0]
    if not subject:
        errors.append('subject line is empty')
    if len(subject) > _SUBJECT_LIMIT:
        errors.append(f'subject is {len(subject)} characters; max {_SUBJECT_LIMIT}')
    if subject.endswith('.'):
        errors.append('subject must not end with a period')
    if not _has_conventional_commit_header(subject):
        allowed = ', '.join(_ALLOWED_TYPES)
        errors.append(
            'subject must match Conventional Commits '
            f'`type(scope): summary` using one of: {allowed}'
        )

    if len(lines) == 1:
        errors.append('message body is missing')
        return tuple(errors)

    if lines[1] != '':
        errors.append('line 2 must be blank')

    body_lines = lines[2:]
    if not any(line.strip() for line in body_lines):
        errors.append('message body is missing')
        return tuple(errors)

    for index, line in enumerate(body_lines, start=3):
        if not line:
            continue
        if len(line) > _BODY_LIMIT:
            errors.append(f'line {index} is {len(line)} characters; max {_BODY_LIMIT}')

    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Validate a commit message against repo commit rules.'
    )
    parser.add_argument(
        '--file',
        type=Path,
        help='Read the commit message from a file.',
    )
    parser.add_argument(
        '--rev',
        help='Read the commit message from a git revision, for example HEAD.',
    )
    args = parser.parse_args(argv)

    try:
        message = _read_message(args)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2

    errors = validate_message(message)
    if not errors:
        print('commit message OK')
        return 0

    for error in errors:
        print(f'error: {error}', file=sys.stderr)
    return 1


def _read_message(args: argparse.Namespace) -> str:
    if args.file is not None and args.rev is not None:
        raise ValueError('use only one of --file or --rev')
    if args.file is not None:
        return args.file.read_text(encoding='utf-8')
    if args.rev is not None:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%B', args.rev],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    if sys.stdin.isatty():
        raise ValueError('provide --file, --rev, or stdin')
    return sys.stdin.read()


def _has_conventional_commit_header(subject: str) -> bool:
    for commit_type in _ALLOWED_TYPES:
        prefix = f'{commit_type}: '
        if subject.startswith(prefix) and subject[len(prefix) :].strip():
            return True

        scope_prefix = f'{commit_type}('
        if not subject.startswith(scope_prefix):
            continue
        closing = subject.find('): ')
        bang_closing = subject.find(')!: ')
        if closing != -1 and subject[closing + 3 :].strip():
            return True
        if bang_closing != -1 and subject[bang_closing + 4 :].strip():
            return True

    return False


if __name__ == '__main__':
    raise SystemExit(main())
