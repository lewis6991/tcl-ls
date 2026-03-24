from __future__ import annotations

import argparse
import platform
import sys

_ARCH_ALIASES = {
    'aarch64': 'arm64',
    'amd64': 'x64',
    'arm64': 'arm64',
    'armv7l': 'armhf',
    'x86_64': 'x64',
}

_RELEASE_PLATFORM_PREFIX = {
    'darwin': 'macos',
    'linux': 'linux',
    'win32': 'windows',
}


def main() -> int:
    parser = argparse.ArgumentParser(description='Resolve host build target names.')
    parser.add_argument(
        'field',
        choices=('archive-extension', 'executable-name', 'release-platform', 'vscode-target'),
    )
    args = parser.parse_args()

    platform_name, arch = _host_target()

    if args.field == 'archive-extension':
        print('zip' if platform_name == 'win32' else 'tar.gz')
    elif args.field == 'executable-name':
        print('tcl-ls.exe' if platform_name == 'win32' else 'tcl-ls')
    elif args.field == 'release-platform':
        print(f'{_RELEASE_PLATFORM_PREFIX[platform_name]}-{arch}')
    else:
        print(f'{platform_name}-{arch}')

    return 0


def _host_target() -> tuple[str, str]:
    platform_name = sys.platform
    if platform_name not in _RELEASE_PLATFORM_PREFIX:
        raise ValueError(f'unsupported platform: {platform_name}')

    machine = platform.machine().lower()
    arch = _ARCH_ALIASES.get(machine)
    if arch is None:
        raise ValueError(f'unsupported architecture: {machine}')
    return platform_name, arch


if __name__ == '__main__':
    raise SystemExit(main())
