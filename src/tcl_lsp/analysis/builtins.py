from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tcl_lsp.analysis.metadata_commands import MetadataCommand, load_metadata_commands
from tcl_lsp.analysis.model import DefinitionTarget
from tcl_lsp.common import Location
from tcl_lsp.metadata_paths import metadata_dir

_META_DIR = metadata_dir()
_CORE_PACKAGE = 'Tcl'
_TCL_86_DIR = Path('tcl8.6')
_BUILTIN_METADATA_PATHS: tuple[tuple[str, Path], ...] = (
    (_CORE_PACKAGE, _TCL_86_DIR / 'tcl.tcl'),
    ('Tk', _TCL_86_DIR / 'tk.tcl'),
    ('tcltest', _TCL_86_DIR / 'tcltest.tcl'),
    ('msgcat', _TCL_86_DIR / 'msgcat.tcl'),
    ('TclOO', _TCL_86_DIR / 'tcloo.tcl'),
    ('clay', Path('tcllib/clay.tcl')),
    ('fileutil', Path('tcllib/fileutil.tcl')),
    ('cmdline', Path('tcllib/cmdline.tcl')),
    ('log', Path('tcllib/log.tcl')),
    ('doctools::text', Path('tcllib/doctools_text.tcl')),
    ('oo::meta', Path('tcllib/oo_meta.tcl')),
)
_PACKAGE_ALIASES = {'tcl::oo': 'TclOO'}


@dataclass(frozen=True, slots=True)
class BuiltinOverload:
    symbol_id: str
    signature: str
    documentation: str
    location: Location


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    name: str
    package: str
    overloads: tuple[BuiltinOverload, ...]


@lru_cache(maxsize=1)
def builtin_commands() -> dict[str, BuiltinCommand]:
    return builtin_commands_by_package()[_CORE_PACKAGE]


@lru_cache(maxsize=1)
def core_annotated_metadata_commands() -> dict[str, MetadataCommand]:
    annotated: dict[str, MetadataCommand] = {}
    for metadata_command in load_metadata_commands(_META_DIR / _TCL_86_DIR / 'tcl.tcl'):
        if not metadata_command.options and not metadata_command.annotations:
            continue
        existing = annotated.get(metadata_command.name)
        if existing is not None and (
            existing.options != metadata_command.options
            or existing.annotations != metadata_command.annotations
        ):
            raise RuntimeError(
                f'Conflicting metadata annotations for core command `{metadata_command.name}`.'
            )
        annotated[metadata_command.name] = metadata_command
    return annotated


@lru_cache(maxsize=1)
def builtin_commands_by_package() -> dict[str, dict[str, BuiltinCommand]]:
    commands_by_package: dict[str, dict[str, BuiltinCommand]] = {}
    for package_name, metadata_relpath in _BUILTIN_METADATA_PATHS:
        commands_by_package[package_name] = _load_metadata_file(
            package_name=package_name,
            metadata_path=_META_DIR / metadata_relpath,
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
        package_commands = builtin_commands_by_package().get(
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


def builtin_commands_any(name: str) -> tuple[BuiltinCommand, ...]:
    matches: list[BuiltinCommand] = []
    for package_commands in builtin_commands_by_package().values():
        command = package_commands.get(name)
        if command is None:
            continue
        matches.append(command)
    return tuple(matches)


def is_builtin_package(package_name: str) -> bool:
    return _canonical_package_name(package_name) in builtin_commands_by_package()


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
        documentation = metadata_command.documentation
        if not documentation:
            raise RuntimeError(f'Builtin command `{metadata_command.name}` is missing documentation.')

        commands.setdefault(metadata_command.name, []).append(
            BuiltinOverload(
                symbol_id=_builtin_symbol_id(
                    package_name,
                    metadata_command.name,
                    metadata_command.name_span.start.offset,
                ),
                signature=_signature(metadata_command.name, metadata_command.signature),
                documentation=documentation,
                location=Location(uri=metadata_command.uri, span=metadata_command.name_span),
            )
        )

    if not commands:
        raise RuntimeError('No builtin command metadata entries were loaded.')

    return {
        name: BuiltinCommand(name=name, package=package_name, overloads=tuple(overloads))
        for name, overloads in commands.items()
    }


def _signature(name: str, parameter_list: str) -> str:
    return f'{name} {{{parameter_list}}}'


def _builtin_symbol_id(package_name: str, name: str, offset: int) -> str:
    return f'builtin::{package_name}::{name}::{offset}'


def _canonical_package_name(package_name: str) -> str:
    return _PACKAGE_ALIASES.get(package_name, package_name)
