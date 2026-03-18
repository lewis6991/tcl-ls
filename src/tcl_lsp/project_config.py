from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.parser import Parser, word_static_text

_CONFIG_FILE_NAME = 'tcllsrc.tcl'
_LIBRARY_PATH_COMMANDS = frozenset({'lib-path', 'library-path'})


@dataclass(frozen=True, slots=True)
class _ConfiguredPaths:
    plugin_paths: tuple[Path, ...]
    library_paths: tuple[Path, ...]


def configured_plugin_paths(path: Path) -> tuple[Path, ...]:
    plugin_paths: dict[Path, None] = {}
    for config_path in config_files(path):
        for plugin_path in load_config_paths(config_path).plugin_paths:
            plugin_paths.setdefault(plugin_path, None)
    return tuple(plugin_paths)


def configured_library_paths(path: Path) -> tuple[Path, ...]:
    library_paths: dict[Path, None] = {}
    for config_path in config_files(path):
        for library_path in load_config_paths(config_path).library_paths:
            library_paths.setdefault(library_path, None)
    return tuple(library_paths)


def config_files(path: Path) -> tuple[Path, ...]:
    start_directory = path if path.is_dir() else path.parent
    matches: list[Path] = []
    for directory in reversed((start_directory, *start_directory.parents)):
        config_path = directory / _CONFIG_FILE_NAME
        if config_path.is_file():
            matches.append(config_path.resolve(strict=False))
    return tuple(matches)


def load_plugin_paths(config_path: Path) -> tuple[Path, ...]:
    return load_config_paths(config_path).plugin_paths


def load_library_paths(config_path: Path) -> tuple[Path, ...]:
    return load_config_paths(config_path).library_paths


def load_config_paths(config_path: Path) -> _ConfiguredPaths:
    text = config_path.read_text(encoding='utf-8')
    parse_result = Parser().parse_document(path=config_path.as_uri(), text=text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid `{_CONFIG_FILE_NAME}`: {message}')

    plugin_paths: dict[Path, None] = {}
    library_paths: dict[Path, None] = {}
    for command in parse_result.script.commands:
        command_name = word_static_text(command.words[0]) if command.words else None
        if command_name is None:
            raise RuntimeError(f'`{_CONFIG_FILE_NAME}` commands must use static command names.')

        if command_name == 'plugin-path':
            target_paths = plugin_paths
        elif command_name in _LIBRARY_PATH_COMMANDS:
            target_paths = library_paths
        else:
            raise RuntimeError(f'Unsupported `{_CONFIG_FILE_NAME}` command `{command_name}`.')

        if len(command.words) != 2:
            raise RuntimeError(
                f'`{_CONFIG_FILE_NAME}` command `{command_name}` must be `{command_name} path`.'
            )

        configured_path = word_static_text(command.words[1])
        if configured_path is None:
            raise RuntimeError(
                f'`{_CONFIG_FILE_NAME}` command `{command_name}` requires a static path.'
            )
        target_paths.setdefault(
            (config_path.parent / configured_path).resolve(strict=False),
            None,
        )
    return _ConfiguredPaths(
        plugin_paths=tuple(plugin_paths),
        library_paths=tuple(library_paths),
    )
