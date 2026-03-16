from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tcl_lsp.analysis.arity import metadata_signature_arity
from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    MetadataOption,
    load_metadata_commands,
)
from tcl_lsp.analysis.model import CommandArity, DefinitionTarget
from tcl_lsp.common import Location
from tcl_lsp.metadata_paths import metadata_dir
from tcl_lsp.parser import Parser, word_static_text

_META_DIR = metadata_dir()
_CORE_PACKAGE = 'Tcl'
_PACKAGE_ALIASES = {'tcl::oo': 'TclOO'}


@dataclass(frozen=True, slots=True)
class BuiltinOverload:
    symbol_id: str
    signature: str
    arity: CommandArity | None
    options: tuple[MetadataOption, ...]
    subcommands: tuple[str, ...]
    documentation: str
    location: Location


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    name: str
    package: str
    metadata_path_name: str
    overloads: tuple[BuiltinOverload, ...]


@lru_cache(maxsize=1)
def builtin_commands() -> dict[str, BuiltinCommand]:
    return builtin_commands_by_package()[_CORE_PACKAGE]


@lru_cache(maxsize=1)
def core_annotated_metadata_commands() -> dict[str, MetadataCommand]:
    return annotated_metadata_commands_by_package()[_CORE_PACKAGE]


@lru_cache(maxsize=1)
def annotated_metadata_commands_by_package() -> dict[str, dict[str, MetadataCommand]]:
    commands_by_package: dict[str, dict[str, MetadataCommand]] = {}
    for package_name, metadata_paths in _builtin_metadata_paths_by_package().items():
        commands_by_package[package_name] = _load_annotated_metadata_package(
            package_name=package_name,
            metadata_paths=metadata_paths,
        )
    return commands_by_package


@lru_cache(maxsize=None)
def annotated_metadata_commands_for_packages(
    required_packages: frozenset[str],
) -> dict[str, tuple[MetadataCommand, ...]]:
    matches_by_name: dict[str, list[MetadataCommand]] = {}

    def add_package(package_name: str) -> None:
        for name, metadata_command in (
            annotated_metadata_commands_by_package().get(package_name, {}).items()
        ):
            matches_by_name.setdefault(name, []).append(metadata_command)

    add_package(_CORE_PACKAGE)
    for package_name in sorted(required_packages):
        add_package(canonical_builtin_package_name(package_name))

    return {name: tuple(matches) for name, matches in matches_by_name.items()}


@lru_cache(maxsize=1)
def builtin_commands_by_package() -> dict[str, dict[str, BuiltinCommand]]:
    commands_by_package: dict[str, dict[str, BuiltinCommand]] = {}
    for package_name, metadata_paths in _builtin_metadata_paths_by_package().items():
        commands_by_package[package_name] = _load_metadata_package(
            package_name=package_name,
            metadata_paths=metadata_paths,
        )
    return commands_by_package


def builtin_command(name: str) -> BuiltinCommand | None:
    return builtin_commands().get(name)


def builtin_command_for_packages(
    name: str,
    required_packages: frozenset[str],
) -> BuiltinCommand | None:
    matches = builtin_commands_for_packages(name, required_packages)
    if len(matches) != 1:
        return None
    return matches[0]


def builtin_commands_for_packages(
    name: str,
    required_packages: frozenset[str],
) -> tuple[BuiltinCommand, ...]:
    matches: list[BuiltinCommand] = []
    seen_packages: set[str] = set()
    core_command = builtin_command(name)
    if core_command is not None:
        seen_packages.add(core_command.package)
        matches.append(core_command)

    for package_name in sorted(required_packages):
        package_commands = builtin_commands_by_package().get(_canonical_package_name(package_name))
        if package_commands is None:
            continue
        package_command = package_commands.get(name)
        if package_command is None or package_command.package in seen_packages:
            continue
        seen_packages.add(package_command.package)
        matches.append(package_command)

    return tuple(matches)


def builtin_commands_any(name: str) -> tuple[BuiltinCommand, ...]:
    matches: list[BuiltinCommand] = []
    for package_commands in builtin_commands_by_package().values():
        command = package_commands.get(name)
        if command is None:
            continue
        matches.append(command)
    return tuple(matches)


def is_builtin_package(package_name: str) -> bool:
    return canonical_builtin_package_name(package_name) in builtin_commands_by_package()


def canonical_builtin_package_name(package_name: str) -> str:
    return _canonical_package_name(package_name)


@lru_cache(maxsize=1)
def builtin_definition_targets() -> tuple[DefinitionTarget, ...]:
    definitions: list[DefinitionTarget] = []
    for package_commands in builtin_commands_by_package().values():
        for builtin in package_commands.values():
            for overload in builtin.overloads:
                definitions.append(
                    DefinitionTarget(
                        symbol_id=overload.symbol_id,
                        name=builtin.name,
                        kind='function',
                        location=overload.location,
                        detail=overload.signature,
                    )
                )
    return tuple(definitions)


def _load_metadata_file(
    *,
    package_name: str,
    metadata_path: Path,
) -> dict[str, BuiltinCommand]:
    commands: dict[str, list[BuiltinOverload]] = {}
    for metadata_command in load_metadata_commands(metadata_path):
        if metadata_command.context_name is not None:
            continue
        documentation = metadata_command.documentation
        if not documentation:
            raise RuntimeError(
                f'Builtin command `{metadata_command.name}` is missing documentation.'
            )

        commands.setdefault(metadata_command.name, []).append(
            BuiltinOverload(
                symbol_id=_builtin_symbol_id(
                    package_name,
                    metadata_command.name,
                    metadata_command.name_span.start.offset,
                ),
                signature=_signature(metadata_command.name, metadata_command.signature),
                arity=metadata_signature_arity(metadata_command.signature),
                options=metadata_command.options,
                subcommands=metadata_command.subcommands,
                documentation=documentation,
                location=Location(uri=metadata_command.uri, span=metadata_command.name_span),
            )
        )

    if not commands:
        raise RuntimeError('No builtin command metadata entries were loaded.')

    return {
        name: BuiltinCommand(
            name=name,
            package=package_name,
            metadata_path_name=metadata_path.name,
            overloads=tuple(overloads),
        )
        for name, overloads in commands.items()
    }


def _load_metadata_package(
    *,
    package_name: str,
    metadata_paths: tuple[Path, ...],
) -> dict[str, BuiltinCommand]:
    package_commands: dict[str, BuiltinCommand] = {}
    for metadata_path in metadata_paths:
        for name, command in _load_metadata_file(
            package_name=package_name,
            metadata_path=metadata_path,
        ).items():
            existing = package_commands.get(name)
            if existing is None:
                package_commands[name] = command
                continue
            if existing.metadata_path_name != command.metadata_path_name:
                raise RuntimeError(
                    f'Builtin command `{name}` is declared in multiple metadata files for '
                    f'package `{package_name}`.'
                )
            package_commands[name] = BuiltinCommand(
                name=name,
                package=package_name,
                metadata_path_name=existing.metadata_path_name,
                overloads=existing.overloads + command.overloads,
            )

    if not package_commands:
        raise RuntimeError(f'No builtin command metadata entries were loaded for `{package_name}`.')
    return package_commands


def _load_annotated_metadata_package(
    *,
    package_name: str,
    metadata_paths: tuple[Path, ...],
) -> dict[str, MetadataCommand]:
    annotated: dict[str, MetadataCommand] = {}
    for metadata_path in metadata_paths:
        for metadata_command in load_metadata_commands(metadata_path):
            if metadata_command.context_name is not None:
                continue
            if (
                not metadata_command.options
                and not metadata_command.subcommands
                and not metadata_command.annotations
            ):
                continue
            existing = annotated.get(metadata_command.name)
            if existing is not None and (
                existing.options != metadata_command.options
                or existing.subcommands != metadata_command.subcommands
                or existing.annotations != metadata_command.annotations
            ):
                raise RuntimeError(
                    f'Conflicting metadata annotations for `{package_name}` command '
                    f'`{metadata_command.name}`.'
                )
            annotated[metadata_command.name] = metadata_command
    return annotated


@lru_cache(maxsize=1)
def _builtin_metadata_paths_by_package() -> dict[str, tuple[Path, ...]]:
    paths_by_package: dict[str, list[Path]] = {}
    for metadata_path in sorted(_META_DIR.rglob('*.tcl')):
        package_name = _declared_builtin_module_name(metadata_path)
        if package_name is None:
            continue
        paths_by_package.setdefault(package_name, []).append(metadata_path)

    if not paths_by_package:
        raise RuntimeError('No builtin metadata files were declared.')

    return {
        package_name: tuple(metadata_paths)
        for package_name, metadata_paths in paths_by_package.items()
    }


@lru_cache(maxsize=None)
def _declared_builtin_module_name(metadata_path: Path) -> str | None:
    parse_result = Parser().parse_document(
        path=metadata_path.as_uri(),
        text=metadata_path.read_text(encoding='utf-8'),
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata file `{metadata_path.name}`: {message}')

    declared_name: str | None = None
    for command in parse_result.script.commands:
        if len(command.words) < 2:
            continue
        if word_static_text(command.words[0]) != 'meta':
            continue
        if word_static_text(command.words[1]) != 'module':
            continue
        if len(command.words) != 3:
            raise RuntimeError(
                f'Builtin metadata file `{metadata_path.name}` must declare modules as '
                '`meta module name`.'
            )

        module_name = word_static_text(command.words[2])
        if module_name is None:
            raise RuntimeError(
                f'Builtin metadata file `{metadata_path.name}` must declare a static module name.'
            )
        if declared_name is not None:
            raise RuntimeError(
                f'Builtin metadata file `{metadata_path.name}` declares multiple module names.'
            )
        declared_name = module_name

    return declared_name


def _signature(name: str, parameter_list: str) -> str:
    return f'{name} {{{parameter_list}}}'


def _builtin_symbol_id(package_name: str, name: str, offset: int) -> str:
    return f'builtin::{package_name}::{name}::{offset}'


def _canonical_package_name(package_name: str) -> str:
    return _PACKAGE_ALIASES.get(package_name, package_name)
