from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / 'pyproject.toml'
PACKAGE_INIT_PATH = ROOT / 'src' / 'tcl_lsp' / '__init__.py'
VSCODE_PACKAGE_JSON_PATH = ROOT / 'editors' / 'vscode' / 'package.json'
VSCODE_PACKAGE_LOCK_PATH = ROOT / 'editors' / 'vscode' / 'package-lock.json'

_PYPROJECT_VERSION_PATTERN = re.compile(r'(?m)^(version\s*=\s*)"[^"]+"$')
_INIT_VERSION_PATTERN = re.compile(r"(?m)^__version__ = '[^']+'$")
_STABLE_VERSION_PATTERN = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
_PRERELEASE_VERSION_PATTERN = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-pre\.([1-9]\d*)$'
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Compute and stamp release versions.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    compute_parser = subparsers.add_parser('compute', help='Compute the release version.')
    compute_parser.add_argument('--channel', choices=('stable', 'prerelease'), required=True)
    compute_parser.add_argument('--run-number', type=int, default=0)

    stamp_parser = subparsers.add_parser('stamp', help='Stamp files with a release version.')
    stamp_parser.add_argument('version')

    args = parser.parse_args()

    if args.command == 'compute':
        version = compute_release_version(
            base_version=read_project_version(),
            channel=args.channel,
            run_number=args.run_number,
        )
        print(version)
        return 0

    stamp_version(args.version)
    return 0


def read_project_version() -> str:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding='utf-8'))
    version = pyproject['project']['version']
    if not isinstance(version, str):
        raise TypeError('project.version must be a string')
    _parse_stable_version(version)
    return version


def compute_release_version(base_version: str, channel: str, run_number: int) -> str:
    major, minor, patch = _parse_stable_version(base_version)
    if channel == 'stable':
        return f'{major}.{minor}.{patch}'
    if run_number <= 0:
        raise ValueError('prerelease builds require a positive run number')

    # Target the next patch as a prerelease so any later stable release sorts after it.
    return f'{major}.{minor}.{patch + 1}-pre.{run_number}'


def stamp_version(version: str) -> None:
    _validate_release_version(version)
    _replace_pattern(PYPROJECT_PATH, _PYPROJECT_VERSION_PATTERN, rf'\1"{version}"')
    _replace_pattern(PACKAGE_INIT_PATH, _INIT_VERSION_PATTERN, f"__version__ = '{version}'")
    _update_json_versions(version)


def _parse_stable_version(version: str) -> tuple[int, int, int]:
    match = _STABLE_VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f'invalid stable version: {version}')
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _validate_release_version(version: str) -> None:
    if _STABLE_VERSION_PATTERN.fullmatch(version) is not None:
        return
    if _PRERELEASE_VERSION_PATTERN.fullmatch(version) is not None:
        return
    raise ValueError(f'invalid release version: {version}')


def _replace_pattern(path: Path, pattern: re.Pattern[str], replacement: str) -> None:
    text = path.read_text(encoding='utf-8')
    updated_text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ValueError(f'could not update version in {path}')
    path.write_text(updated_text, encoding='utf-8')


def _update_json_versions(version: str) -> None:
    package_json = json.loads(VSCODE_PACKAGE_JSON_PATH.read_text(encoding='utf-8'))
    package_json['version'] = version
    VSCODE_PACKAGE_JSON_PATH.write_text(json.dumps(package_json, indent=2) + '\n', encoding='utf-8')

    package_lock = json.loads(VSCODE_PACKAGE_LOCK_PATH.read_text(encoding='utf-8'))
    package_lock = _strip_package_lock_resolved(package_lock)
    package_lock['version'] = version
    if package_lock.get('packages', {}).get('') is not None:
        package_lock['packages']['']['version'] = version
    VSCODE_PACKAGE_LOCK_PATH.write_text(json.dumps(package_lock, indent=2) + '\n', encoding='utf-8')


def _strip_package_lock_resolved(value: object) -> object:
    if isinstance(value, list):
        return [_strip_package_lock_resolved(item) for item in value]
    if not isinstance(value, dict):
        return value

    cleaned: dict[str, object] = {}
    for key, item in value.items():
        if key == 'resolved':
            continue
        cleaned[key] = _strip_package_lock_resolved(item)
    return cleaned


if __name__ == '__main__':
    raise SystemExit(main())
