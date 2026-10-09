from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    command_tree_prefixes,
    load_metadata_commands,
    metadata_environment_names,
    metadata_file_summary,
)
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.metadata_paths import MetadataRegistry

type CommandKey = tuple[str | None, str]


@dataclass(frozen=True, slots=True)
class _MetadataLayer:
    commands: tuple[MetadataCommand, ...]
    language_extends: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class MetadataView:
    """Metadata roots followed by the selected environments, in stack order."""

    commands: Mapping[CommandKey, tuple[MetadataCommand, ...]]
    environment_commands: Mapping[str, MetadataCommand]
    language_extends: Mapping[str, bool]


@metadata_lru_cache(maxsize=128)
def metadata_view(registry: MetadataRegistry) -> MetadataView:
    # File discovery and parsing do not depend on the active environment stack.
    base, environments = _metadata_layers(registry.with_environments(()))
    layers = list(base)
    occupied: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
    for layer in base:
        _overlay(
            occupied,
            _group_commands(
                command
                for command in layer.commands
                if command.context_name is not None or command.module_name == 'Tcl'
            ),
        )

    for name in registry.environments:
        if name not in environments:
            raise RuntimeError(f'Unknown metadata environment `{name}`.')
        commands: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
        extends: dict[str, bool] = {}
        for layer in environments[name]:
            _overlay(commands, _group_commands(layer.commands))
            extends.update(layer.language_extends)
        selected = {
            key: overloads
            for key, overloads in commands.items()
            if any(command.is_override for command in overloads)
            or (key[0], key[1].split(' ', maxsplit=1)[0]) not in occupied
        }
        _overlay(occupied, selected)
        layers.append(
            _MetadataLayer(
                tuple(command for overloads in selected.values() for command in overloads),
                tuple(extends.items()),
            )
        )

    effective: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
    for layer in layers:
        _overlay(effective, _group_commands(layer.commands))
    return MetadataView(
        commands=MappingProxyType(effective),
        environment_commands=MappingProxyType(
            {
                name: overloads[0]
                for (context, name), overloads in occupied.items()
                if context is None and overloads[0].module_name in environments
            }
        ),
        language_extends=MappingProxyType(
            {name: extends for layer in layers for name, extends in layer.language_extends}
        ),
    )


@metadata_lru_cache(maxsize=128)
def _metadata_layers(
    registry: MetadataRegistry,
) -> tuple[tuple[_MetadataLayer, ...], dict[str, tuple[_MetadataLayer, ...]]]:
    environment_names = metadata_environment_names(registry)
    base: list[_MetadataLayer] = []
    environments: dict[str, list[_MetadataLayer]] = {name: [] for name in environment_names}
    for _, paths in registry.metadata_file_layers():
        commands_by_environment: dict[str | None, list[MetadataCommand]] = {}
        extends_by_environment: dict[str | None, dict[str, bool]] = {}
        for path in paths:
            for command in load_metadata_commands(
                path, alias_paths=registry.metadata_files(), revision=registry.revision
            ):
                environment = (
                    command.module_name if command.module_name in environment_names else None
                )
                commands_by_environment.setdefault(environment, []).append(command)
            for module, name, extends_tcl in metadata_file_summary(
                path, revision=registry.revision
            ).language_extends:
                environment = module if module in environment_names else None
                extends = extends_by_environment.setdefault(environment, {})
                extends[name] = extends.get(name, False) or extends_tcl
        for environment in dict.fromkeys((*commands_by_environment, *extends_by_environment)):
            layer = _MetadataLayer(
                tuple(commands_by_environment.get(environment, ())),
                tuple(extends_by_environment.get(environment, {}).items()),
            )
            (base if environment is None else environments[environment]).append(layer)
    return tuple(base), {name: tuple(layers) for name, layers in environments.items()}


def _group_commands(
    commands: Iterable[MetadataCommand],
) -> dict[CommandKey, tuple[MetadataCommand, ...]]:
    grouped: dict[CommandKey, list[MetadataCommand]] = {}
    for command in commands:
        grouped.setdefault((command.context_name, command.name), []).append(command)
    return {key: tuple(overloads) for key, overloads in grouped.items()}


def _overlay(
    commands: dict[CommandKey, tuple[MetadataCommand, ...]],
    additions: dict[CommandKey, tuple[MetadataCommand, ...]],
) -> None:
    for context, name in tuple(commands):
        if any((context, prefix) in additions for prefix in command_tree_prefixes(name)):
            del commands[context, name]
    commands.update(additions)
