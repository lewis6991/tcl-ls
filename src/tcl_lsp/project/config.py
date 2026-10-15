from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Diagnostic
from tcl_lsp.parser import ParseResult, word_static_text
from tcl_lsp.parser.expr import Expr, parse_expr
from tcl_lsp.parser.model import Command
from tcl_lsp.project.context import ConfigContext
from tcl_lsp.project.declarations import (
    DeclarationError,
    DeclarationGroup,
    DeclarationSnapshot,
    MetadataPath,
)
from tcl_lsp.project.diagnostics import DiagnosticRule, parse_diagnostic_rule
from tcl_lsp.project.evaluation import evaluate_config
from tcl_lsp.project.paths import candidate_package_roots

_CONFIG_FILE_NAME = 'tcllsrc.tcl'
_LIBRARY_PATH_COMMANDS = frozenset({'lib-path', 'library-path'})


@dataclass(frozen=True, slots=True)
class ModuleRule:
    name: str
    condition: Expr


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    metadata_paths: tuple[MetadataPath, ...]
    library_paths: tuple[Path, ...]
    module_rules: tuple[ModuleRule, ...] = ()
    diagnostic_rules: tuple[DiagnosticRule, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    declarations: DeclarationGroup | None = None


def is_config_file(path: Path | None) -> bool:
    return path is not None and path.name == _CONFIG_FILE_NAME


def configured_module_rules(
    path: Path, *, context: ConfigContext | None = None
) -> tuple[ModuleRule, ...]:
    context = context or config_context(path)
    return tuple(
        rule
        for config_path in config_files(path)
        for rule in load_config_paths(config_path, context=context).module_rules
    )


def configured_diagnostic_rules(
    path: Path, *, context: ConfigContext | None = None
) -> tuple[DiagnosticRule, ...]:
    context = context or config_context(path)
    return tuple(
        rule
        for config_path in config_files(path)
        for rule in load_config_paths(config_path, context=context).diagnostic_rules
    )


def configured_metadata_paths(
    path: Path, *, context: ConfigContext | None = None
) -> tuple[MetadataPath, ...]:
    context = context or config_context(path)
    metadata_paths: dict[MetadataPath, None] = {}
    for config_path in config_files(path):
        for metadata_path in load_config_paths(config_path, context=context).metadata_paths:
            metadata_paths.setdefault(metadata_path, None)
    return tuple(metadata_paths)


def configured_library_paths(
    path: Path, *, context: ConfigContext | None = None
) -> tuple[Path, ...]:
    context = context or config_context(path)
    library_paths: dict[Path, None] = {}
    for config_path in config_files(path):
        for library_path in load_config_paths(config_path, context=context).library_paths:
            library_paths.setdefault(library_path, None)
    return tuple(library_paths)


def config_files(path: Path, *, include_user: bool = True) -> tuple[Path, ...]:
    """Find settings in load order; exclude user settings when finding project roots."""
    start_directory = path if path.is_dir() else path.parent
    user_config = _user_config_file().resolve(strict=False)
    candidates = [user_config] if include_user else []
    for directory in reversed((start_directory, *start_directory.parents)):
        candidates.append(directory / _CONFIG_FILE_NAME)
    matches: dict[Path, None] = {}
    source_path = path.resolve(strict=False)
    for config_path in candidates:
        if not config_path.is_file():
            continue
        resolved = config_path.resolve(strict=False)
        if not include_user and resolved == user_config:
            continue
        # A config is analyzed with its parent settings. Its own contents can
        # be incomplete or invalid while the user edits them.
        if resolved != source_path:
            matches.setdefault(resolved, None)
    return tuple(matches)


def _user_config_file() -> Path:
    directory = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    if not directory.is_absolute():
        directory = Path.home() / '.config'
    return directory / 'tcl-ls' / _CONFIG_FILE_NAME


def config_context(path: Path, *, workspace_root: Path | None = None) -> ConfigContext:
    path = path.resolve(strict=False)
    if workspace_root is None:
        projects = config_files(path, include_user=False)
        if projects:
            workspace_root = projects[-1].parent
        elif package_roots := candidate_package_roots(path):
            workspace_root = package_roots[0]
        else:
            workspace_root = path if path.is_dir() else path.parent
    return ConfigContext(workspace_root.resolve(strict=False))


def load_metadata_paths(config_path: Path) -> tuple[MetadataPath, ...]:
    return load_config_paths(config_path).metadata_paths


def load_library_paths(config_path: Path) -> tuple[Path, ...]:
    return load_config_paths(config_path).library_paths


def load_config_paths(config_path: Path, *, context: ConfigContext | None = None) -> ProjectConfig:
    try:
        root = evaluate_config(config_path, context or config_context(config_path))
        config = _snapshot_config(root.path, root.snapshot)
    except DeclarationError as exc:
        raise RuntimeError(f'Invalid `{_CONFIG_FILE_NAME}`: {exc}') from exc
    if config.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in config.diagnostics)
        raise RuntimeError(f'Invalid `{_CONFIG_FILE_NAME}`: {message}')
    return replace(config, metadata_paths=(root,)) if config.metadata_paths else config


@metadata_lru_cache(maxsize=256)
def _snapshot_config(path: Path, snapshot: DeclarationSnapshot) -> ProjectConfig:
    return _config_from_declarations(snapshot.declarations, path)


def parse_config(
    parse_result: ParseResult, *, directory: Path, context: ConfigContext | None = None
) -> ProjectConfig:
    if parse_result.diagnostics:
        return ProjectConfig((), (), diagnostics=parse_result.diagnostics)

    config_path = directory / _CONFIG_FILE_NAME
    try:
        root = evaluate_config(
            config_path, context or config_context(config_path), buffer=parse_result
        )
    except (DeclarationError, RuntimeError) as exc:
        return ProjectConfig(
            (),
            (),
            diagnostics=(
                Diagnostic(
                    span=exc.span
                    if isinstance(exc, DeclarationError)
                    else parse_result.script.span,
                    message=str(exc),
                    severity='error',
                    code='invalid-project-config',
                    source='tcl-ls',
                ),
            ),
        )
    return _config_from_declarations(root.snapshot.declarations, config_path)


def _config_from_declarations(declarations: DeclarationGroup, config_path: Path) -> ProjectConfig:
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
        match values:
            case [str(name)] if name:
                condition_text = '1'
            case [str(name), 'when', str(condition_text)] if name and condition_text:
                pass
            case _:
                raise RuntimeError('Module rules must be `module name ?when {condition}?`.')
        condition = parse_expr(condition_text)
        if condition is None:
            raise RuntimeError(f'Invalid module condition for `{name}`.')
        return ModuleRule(name, condition)
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
