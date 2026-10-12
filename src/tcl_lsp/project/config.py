from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.common import Diagnostic
from tcl_lsp.parser import Parser, ParseResult, word_static_text
from tcl_lsp.parser.expr import parse_expr
from tcl_lsp.parser.model import Command
from tcl_lsp.project.declarations import DeclarationError, DeclarationGroup, read_declarations
from tcl_lsp.project.diagnostics import DiagnosticRule, parse_diagnostic_rule

_CONFIG_FILE_NAME = 'tcllsrc.tcl'
_LIBRARY_PATH_COMMANDS = frozenset({'lib-path', 'library-path'})


@dataclass(frozen=True, slots=True)
class ModuleRule:
    name: str
    condition: str


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    metadata_paths: tuple[Path, ...]
    library_paths: tuple[Path, ...]
    module_rules: tuple[ModuleRule, ...] = ()
    diagnostic_rules: tuple[DiagnosticRule, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    declarations: DeclarationGroup | None = None


def is_config_file(path: Path | None) -> bool:
    return path is not None and path.name == _CONFIG_FILE_NAME


def configured_module_rules(path: Path) -> tuple[ModuleRule, ...]:
    return tuple(
        rule
        for config_path in config_files(path)
        for rule in load_config_paths(config_path).module_rules
    )


def configured_diagnostic_rules(path: Path) -> tuple[DiagnosticRule, ...]:
    return tuple(
        rule
        for config_path in config_files(path)
        for rule in load_config_paths(config_path).diagnostic_rules
    )


def configured_metadata_paths(path: Path) -> tuple[Path, ...]:
    metadata_paths: dict[Path, None] = {}
    for config_path in config_files(path):
        for metadata_path in load_config_paths(config_path).metadata_paths:
            metadata_paths.setdefault(metadata_path, None)
    return tuple(metadata_paths)


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
        # A config is analyzed with its parent settings. Its own contents can
        # be incomplete or invalid while the user edits them.
        if config_path != path and config_path.is_file():
            matches.append(config_path.resolve(strict=False))
    return tuple(matches)


def load_metadata_paths(config_path: Path) -> tuple[Path, ...]:
    return load_config_paths(config_path).metadata_paths


def load_library_paths(config_path: Path) -> tuple[Path, ...]:
    return load_config_paths(config_path).library_paths


def load_config_paths(config_path: Path) -> ProjectConfig:
    text = config_path.read_text(encoding='utf-8')
    parse_result = Parser().parse_document(path=config_path.as_uri(), text=text)
    config = parse_config(parse_result, directory=config_path.parent.resolve(strict=False))
    if config.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in config.diagnostics)
        raise RuntimeError(f'Invalid `{_CONFIG_FILE_NAME}`: {message}')
    return config


def parse_config(parse_result: ParseResult, *, directory: Path) -> ProjectConfig:
    if parse_result.diagnostics:
        return ProjectConfig((), (), diagnostics=parse_result.diagnostics)

    config_path = directory / _CONFIG_FILE_NAME
    try:
        declarations = read_declarations(parse_result, path=config_path, recover=True)
    except DeclarationError as exc:
        return ProjectConfig(
            (),
            (),
            diagnostics=(
                Diagnostic(
                    span=exc.span,
                    message=str(exc),
                    severity='error',
                    code='invalid-project-config',
                    source='tcl-ls',
                ),
            ),
        )
    has_metadata = False
    library_paths: dict[Path, None] = {}
    module_rules: list[ModuleRule] = []
    diagnostic_rules: list[DiagnosticRule] = []
    diagnostics = [
        Diagnostic(
            span=error.span,
            message=str(error),
            severity='error',
            code='invalid-project-config',
            source='tcl-ls',
        )
        for error in declarations.failures()
    ]
    for block, include_site in declarations.located_blocks():
        has_metadata |= block.module is not None
        for command in block.commands:
            if word_static_text(command.words[0]) == 'meta':
                has_metadata = True
                continue
            try:
                if block.module is not None:
                    raise RuntimeError(
                        'Module blocks only accept metadata declarations and source includes.'
                    )
                entry = _parse_config_command(command, directory=block.path.parent)
            except RuntimeError as exc:
                diagnostics.append(
                    Diagnostic(
                        span=include_site[1] if include_site is not None else command.span,
                        message=str(exc),
                        severity='error',
                        code='invalid-project-config',
                        source='tcl-ls',
                    )
                )
                continue
            if isinstance(entry, DiagnosticRule):
                diagnostic_rules.append(entry)
            elif isinstance(entry, ModuleRule):
                module_rules.append(entry)
            else:
                _, path = entry
                library_paths.setdefault(path, None)
    return ProjectConfig(
        metadata_paths=(config_path,) if has_metadata else (),
        library_paths=tuple(library_paths),
        module_rules=tuple(module_rules),
        diagnostic_rules=tuple(diagnostic_rules),
        diagnostics=tuple(sorted(diagnostics, key=lambda diagnostic: diagnostic.span.start.offset)),
        declarations=declarations,
    )


def _parse_config_command(
    command: Command, *, directory: Path
) -> DiagnosticRule | ModuleRule | tuple[str, Path]:
    words = tuple(None if word.expanded else word_static_text(word) for word in command.words)
    command_name, *values = words
    if command_name is None:
        raise RuntimeError(f'`{_CONFIG_FILE_NAME}` commands must use static command names.')
    if command_name == 'diagnostic':
        return parse_diagnostic_rule(tuple(values), directory=directory)
    if command_name == 'module':
        if len(values) != 3 or not values[0] or values[1] != 'when' or not values[2]:
            raise RuntimeError('Module rules must be `module name when {condition}`.')
        if parse_expr(values[2]) is None:
            raise RuntimeError(f'Invalid module condition for `{values[0]}`.')
        return ModuleRule(values[0], values[2])
    if command_name not in _LIBRARY_PATH_COMMANDS:
        raise RuntimeError(f'Unsupported `{_CONFIG_FILE_NAME}` command `{command_name}`.')
    if len(values) != 1:
        raise RuntimeError(
            f'`{_CONFIG_FILE_NAME}` command `{command_name}` must be `{command_name} path`.'
        )
    if values[0] is None:
        raise RuntimeError(
            f'`{_CONFIG_FILE_NAME}` command `{command_name}` requires a static path.'
        )
    return command_name, (directory / values[0]).resolve(strict=False)


__all__ = [
    'config_files',
    'configured_diagnostic_rules',
    'configured_library_paths',
    'configured_metadata_paths',
    'configured_module_rules',
    'is_config_file',
    'load_config_paths',
    'load_library_paths',
    'load_metadata_paths',
    'parse_config',
]
