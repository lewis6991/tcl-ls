from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tcl_lsp.analysis.metadata_commands import (
    MetadataCommand,
    command_tree_prefixes,
    load_metadata_commands,
    metadata_file_summary,
    metadata_module_names,
)
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.metadata_paths import MetadataRegistry

# TclOO ships with the supported Tcl runtime. Other modules need selection.
_DEFAULT_MODULES = frozenset({'Tcl', 'TclOO'})

type CommandKey = tuple[str | None, str]


@dataclass(frozen=True, slots=True)
class _MetadataLayer:
    commands: tuple[MetadataCommand, ...]
    language_extends: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class MetadataView:
    """Metadata roots followed by the selected modules, in stack order."""

    commands: Mapping[CommandKey, tuple[MetadataCommand, ...]]
    module_commands: Mapping[str, MetadataCommand]
    language_extends: Mapping[str, bool]


@metadata_lru_cache(maxsize=128)
def metadata_view(registry: MetadataRegistry) -> MetadataView:
    # File discovery and parsing do not depend on the active module stack.
    base, modules = _metadata_layers(registry.with_modules(()))
    commands: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
    occupied: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
    language_extends: dict[str, bool] = {}
    for layer in base:
        _overlay(commands, _group_commands(layer.commands))
        # File-scoped annotations do not declare globally available commands.
        _overlay(
            occupied,
            _group_commands(
                command
                for command in layer.commands
                if command.context_name is not None or command.module_name is not None
            ),
        )
        language_extends.update(layer.language_extends)

    for name in dict.fromkeys(registry.modules):
        if name not in modules:
            raise RuntimeError(f'Unknown metadata module `{name}`.')
        additions: dict[CommandKey, tuple[MetadataCommand, ...]] = {}
        for layer in modules[name]:
            _overlay(additions, _group_commands(layer.commands))
            language_extends.update(layer.language_extends)
        selected = {
            key: overloads
            for key, overloads in additions.items()
            if any(command.is_override for command in overloads)
            or (key[0], key[1].split(' ', maxsplit=1)[0]) not in occupied
        }
        _overlay(occupied, selected)
        _overlay(commands, selected)

    return MetadataView(
        commands=MappingProxyType(commands),
        module_commands=MappingProxyType(
            {
                name: overloads[0]
                for (context, name), overloads in occupied.items()
                if context is None
            }
        ),
        language_extends=MappingProxyType(language_extends),
    )


@metadata_lru_cache(maxsize=128)
def _metadata_layers(
    registry: MetadataRegistry,
) -> tuple[tuple[_MetadataLayer, ...], dict[str, tuple[_MetadataLayer, ...]]]:
    module_names = metadata_module_names(registry)
    base: list[_MetadataLayer] = []
    modules: dict[str, list[_MetadataLayer]] = {name: [] for name in module_names}
    for _, paths in registry.metadata_file_layers():
        commands_by_module: dict[str | None, list[MetadataCommand]] = {}
        extends_by_module: dict[str | None, dict[str, bool]] = {}
        for path in paths:
            for command in load_metadata_commands(
                path, alias_paths=registry.metadata_files(), revision=registry.revision
            ):
                module = (
                    command.module_name if command.module_name not in _DEFAULT_MODULES else None
                )
                commands_by_module.setdefault(module, []).append(command)
            for module, name, extends_tcl in metadata_file_summary(
                path, revision=registry.revision
            ).language_extends:
                module = module if module not in _DEFAULT_MODULES else None
                extends = extends_by_module.setdefault(module, {})
                extends[name] = extends.get(name, False) or extends_tcl
        for module in dict.fromkeys((*commands_by_module, *extends_by_module)):
            layer = _MetadataLayer(
                tuple(commands_by_module.get(module, ())),
                tuple(extends_by_module.get(module, {}).items()),
            )
            (base if module is None else modules[module]).append(layer)
    return tuple(base), {name: tuple(layers) for name, layers in modules.items()}


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
