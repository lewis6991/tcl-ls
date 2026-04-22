from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lsprotocol import types

from tcl_lsp.analysis.arity import metadata_signature_arity
from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    MetadataOption,
    load_metadata_commands,
)
from tcl_lsp.analysis.model import CommandArity, DefinitionTarget
from tcl_lsp.analysis.signature_matching import display_metadata_signature
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Span, lsp_location
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY, MetadataRegistry
from tcl_lsp.parser import Parser, word_static_text

_CORE_PACKAGE = 'Tcl'
_PACKAGE_ALIASES = {
    # Some bundled tcllib metadata is shipped for specific subpackages even when
    # callers commonly `package require` the umbrella package.
    'struct': 'struct::set',
    'tcl::oo': 'TclOO',
}


@dataclass(frozen=True, slots=True)
class BuiltinOverload:
    symbol_id: str
    signature: str
    match_signature: str
    arity: CommandArity | None
    options: tuple[MetadataOption, ...]
    subcommands: tuple[str, ...]
    documentation: str | None
    location: types.Location
    span: Span


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    name: str
    package: str
    metadata_path_name: str
    overloads: tuple[BuiltinOverload, ...]


def builtin_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[str, BuiltinCommand]:
    return _builtin_commands(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _builtin_commands(metadata_registry: MetadataRegistry) -> dict[str, BuiltinCommand]:
    return builtin_commands_by_package(metadata_registry=metadata_registry)[_CORE_PACKAGE]


def core_annotated_metadata_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[str, MetadataCommand]:
    return _core_annotated_metadata_commands(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _core_annotated_metadata_commands(
    metadata_registry: MetadataRegistry,
) -> dict[str, MetadataCommand]:
    return annotated_metadata_commands_by_package(metadata_registry=metadata_registry)[
        _CORE_PACKAGE
    ]


def annotated_metadata_commands_by_package(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[str, dict[str, MetadataCommand]]:
    return _annotated_metadata_commands_by_package(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _annotated_metadata_commands_by_package(
    metadata_registry: MetadataRegistry,
) -> dict[str, dict[str, MetadataCommand]]:
    commands_by_package: dict[str, dict[str, MetadataCommand]] = {}
    for package_name, metadata_path_layers in _builtin_metadata_path_layers_by_package(
        metadata_registry
    ).items():
        commands_by_package[package_name] = _load_annotated_metadata_package(
            package_name=package_name,
            metadata_path_layers=metadata_path_layers,
        )
    return commands_by_package


def annotated_metadata_commands_for_packages(
    required_packages: frozenset[str],
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[str, tuple[MetadataCommand, ...]]:
    return _annotated_metadata_commands_for_packages(required_packages, metadata_registry)


@metadata_lru_cache(maxsize=None)
def _annotated_metadata_commands_for_packages(
    required_packages: frozenset[str],
    metadata_registry: MetadataRegistry,
) -> dict[str, tuple[MetadataCommand, ...]]:
    matches_by_name: dict[str, list[MetadataCommand]] = {}

    def add_package(package_name: str) -> None:
        for name, metadata_command in (
            annotated_metadata_commands_by_package(metadata_registry=metadata_registry)
            .get(package_name, {})
            .items()
        ):
            matches_by_name.setdefault(name, []).append(metadata_command)

    add_package(_CORE_PACKAGE)
    for package_name in sorted(required_packages):
        add_package(canonical_builtin_package_name(package_name))

    return {name: tuple(matches) for name, matches in matches_by_name.items()}


def builtin_commands_by_package(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[str, dict[str, BuiltinCommand]]:
    return _builtin_commands_by_package(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _builtin_commands_by_package(
    metadata_registry: MetadataRegistry,
) -> dict[str, dict[str, BuiltinCommand]]:
    commands_by_package: dict[str, dict[str, BuiltinCommand]] = {}
    for package_name, metadata_path_layers in _builtin_metadata_path_layers_by_package(
        metadata_registry
    ).items():
        commands_by_package[package_name] = _load_metadata_package(
            package_name=package_name,
            metadata_path_layers=metadata_path_layers,
        )
    return commands_by_package


def builtin_command(
    name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> BuiltinCommand | None:
    return builtin_commands(metadata_registry=metadata_registry).get(name)


def builtin_command_for_packages(
    name: str,
    required_packages: frozenset[str],
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> BuiltinCommand | None:
    matches = builtin_commands_for_packages(
        name,
        required_packages,
        metadata_registry=metadata_registry,
    )
    if len(matches) != 1:
        return None
    return matches[0]


def builtin_commands_for_packages(
    name: str,
    required_packages: frozenset[str],
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[BuiltinCommand, ...]:
    matches: list[BuiltinCommand] = []
    seen_packages: set[str] = set()
    core_command = builtin_command(name, metadata_registry=metadata_registry)
    if core_command is not None:
        seen_packages.add(core_command.package)
        matches.append(core_command)

    for package_name in sorted(required_packages):
        package_commands = builtin_commands_by_package(metadata_registry=metadata_registry).get(
            _canonical_package_name(package_name)
        )
        if package_commands is None:
            continue
        package_command = package_commands.get(name)
        if package_command is None or package_command.package in seen_packages:
            continue
        seen_packages.add(package_command.package)
        matches.append(package_command)

    return tuple(matches)


def builtin_commands_any(
    name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[BuiltinCommand, ...]:
    matches: list[BuiltinCommand] = []
    for package_commands in builtin_commands_by_package(
        metadata_registry=metadata_registry
    ).values():
        command = package_commands.get(name)
        if command is None:
            continue
        matches.append(command)
    return tuple(matches)


def is_builtin_package(
    package_name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> bool:
    return canonical_builtin_package_name(package_name) in builtin_commands_by_package(
        metadata_registry=metadata_registry
    )


def canonical_builtin_package_name(package_name: str) -> str:
    return _canonical_package_name(package_name)


def builtin_definition_targets(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[DefinitionTarget, ...]:
    return _builtin_definition_targets(metadata_registry)


@metadata_lru_cache(maxsize=1)
def _builtin_definition_targets(
    metadata_registry: MetadataRegistry,
) -> tuple[DefinitionTarget, ...]:
    definitions: list[DefinitionTarget] = []
    for package_commands in builtin_commands_by_package(
        metadata_registry=metadata_registry
    ).values():
        for builtin in package_commands.values():
            for overload in builtin.overloads:
                definitions.append(
                    DefinitionTarget(
                        symbol_id=overload.symbol_id,
                        name=builtin.name,
                        kind='function',
                        location=overload.location,
                        span=overload.span,
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
        commands.setdefault(metadata_command.name, []).append(
            BuiltinOverload(
                symbol_id=_builtin_symbol_id(
                    package_name,
                    metadata_command.name,
                    metadata_command.signature,
                    metadata_command.name_span.start.offset,
                ),
                signature=_signature(
                    metadata_command.name,
                    display_metadata_signature(metadata_command.signature),
                ),
                match_signature=metadata_command.signature,
                arity=metadata_signature_arity(metadata_command.signature),
                options=metadata_command.options,
                subcommands=metadata_command.subcommands,
                documentation=metadata_command.documentation,
                location=lsp_location(metadata_command.uri, metadata_command.name_span),
                span=metadata_command.name_span,
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
    metadata_path_layers: tuple[tuple[Path, ...], ...],
) -> dict[str, BuiltinCommand]:
    package_commands: dict[str, BuiltinCommand] = {}
    for metadata_paths in metadata_path_layers:
        layer_commands: dict[str, BuiltinCommand] = {}
        for metadata_path in metadata_paths:
            for name, command in _load_metadata_file(
                package_name=package_name,
                metadata_path=metadata_path,
            ).items():
                if name in layer_commands:
                    raise RuntimeError(
                        f'Conflicting builtin metadata for `{package_name}` command `{name}`.'
                    )
                layer_commands[name] = command
        # Later metadata roots override earlier command trees. Within one root,
        # duplicate command declarations are treated as conflicting metadata.
        _discard_overridden_commands(package_commands, layer_commands)
        package_commands.update(layer_commands)

    if not package_commands:
        raise RuntimeError(f'No builtin command metadata entries were loaded for `{package_name}`.')
    return package_commands


def _load_annotated_metadata_package(
    *,
    package_name: str,
    metadata_path_layers: tuple[tuple[Path, ...], ...],
) -> dict[str, MetadataCommand]:
    annotated: dict[str, MetadataCommand] = {}
    for metadata_paths in metadata_path_layers:
        layer_override_names: dict[str, None] = {}
        layer_annotated: dict[str, MetadataCommand] = {}
        for metadata_path in metadata_paths:
            file_override_names, file_annotated = _annotated_entries_for_file(
                package_name=package_name,
                metadata_path=metadata_path,
            )
            for command_name in file_override_names:
                if command_name in layer_override_names:
                    raise RuntimeError(
                        f'Conflicting metadata annotations for `{package_name}` command '
                        f'`{command_name}`.'
                    )
                layer_override_names[command_name] = None
            layer_annotated.update(file_annotated)
        _discard_overridden_commands(annotated, layer_override_names)
        annotated.update(layer_annotated)
    return annotated


@metadata_lru_cache(maxsize=1)
def _builtin_metadata_path_layers_by_package(
    metadata_registry: MetadataRegistry,
) -> dict[str, tuple[tuple[Path, ...], ...]]:
    path_layers_by_package: dict[str, list[tuple[Path, ...]]] = {}
    for _, layer_paths in metadata_registry.metadata_file_layers():
        layer_paths_by_package: dict[str, list[Path]] = {}
        for metadata_path in layer_paths:
            package_name = _declared_builtin_module_name(metadata_path)
            if package_name is None:
                continue
            layer_paths_by_package.setdefault(package_name, []).append(metadata_path)
        for package_name, package_paths in layer_paths_by_package.items():
            path_layers_by_package.setdefault(package_name, []).append(tuple(package_paths))

    if not path_layers_by_package:
        raise RuntimeError('No builtin metadata files were declared.')

    return {
        package_name: tuple(metadata_path_layers)
        for package_name, metadata_path_layers in path_layers_by_package.items()
    }


def _discard_overridden_commands(
    commands: dict[str, Any],
    override_commands: dict[str, Any],
) -> None:
    override_names = tuple(override_commands)
    for existing_name in tuple(commands):
        if any(
            existing_name == override_name or existing_name.startswith(f'{override_name} ')
            for override_name in override_names
        ):
            commands.pop(existing_name, None)


@metadata_lru_cache(maxsize=None)
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


def _annotated_entries_for_file(
    *,
    package_name: str,
    metadata_path: Path,
) -> tuple[tuple[str, ...], dict[str, MetadataCommand]]:
    override_entries: dict[str, MetadataCommand | None] = {}
    annotated: dict[str, MetadataCommand] = {}
    for metadata_command in load_metadata_commands(metadata_path):
        if metadata_command.context_name is not None:
            continue
        annotated_command = (
            metadata_command
            if (
                metadata_command.options
                or metadata_command.subcommands
                or metadata_command.annotations
            )
            else None
        )
        existing = override_entries.get(metadata_command.name)
        if metadata_command.name in override_entries:
            if annotated_command is None:
                continue
            if existing is None:
                override_entries[metadata_command.name] = annotated_command
                annotated[metadata_command.name] = annotated_command
                continue
            if (
                existing.options == annotated_command.options
                and existing.subcommands == annotated_command.subcommands
                and existing.annotations == annotated_command.annotations
            ):
                continue
            raise RuntimeError(
                f'Conflicting metadata annotations for `{package_name}` command '
                f'`{metadata_command.name}`.'
            )
        override_entries[metadata_command.name] = annotated_command
        if annotated_command is not None:
            annotated[metadata_command.name] = annotated_command
    return tuple(override_entries), annotated


def _signature(name: str, parameter_list: str) -> str:
    return f'{name} {{{parameter_list}}}'


def _builtin_symbol_id(package_name: str, name: str, signature: str, offset: int) -> str:
    return f'builtin::{package_name}::{name}::{signature}::{offset}'


def _canonical_package_name(package_name: str) -> str:
    return _PACKAGE_ALIASES.get(package_name, package_name)
