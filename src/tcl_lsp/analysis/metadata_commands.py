from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.facts.utils import normalize_command_name, qualify_namespace
from tcl_lsp.analysis.model import BINDING_KINDS, BindingKind, CommandVisibility
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.metadata_paths import (
    DEFAULT_METADATA_REGISTRY,
    MetadataCatalog,
    MetadataRegistry,
    MetadataRevision,
    metadata_lookup_names,
)
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import BareWord, BracedWord, Command, Token, Word
from tcl_lsp.project.declarations import (
    DeclarationBlock,
    DeclarationError,
    DeclarationGroup,
    MetadataPath,
    ModuleScope,
    load_declarations,
)

_MISSING = object()
type SourceBase = Literal['caller', 'definition']
type MetadataOptionKind = Literal['flag', 'value', 'stop']
type OptionScanState = Literal[
    'ok', 'dynamic', 'unstable', 'unknown-option', 'missing-option-value'
]


@dataclass(frozen=True, slots=True)
class MetadataSelector:
    start_index: int
    all_remaining: bool
    list_mode: bool
    after_options: bool
    step: int = 1
    start_from_end: bool = False
    end_index: int | None = None
    end_from_end: bool = False

    @property
    def has_relative_bounds(self) -> bool:
        return self.start_from_end or self.end_from_end

    @property
    def selects_single_argument(self) -> bool:
        return not self.all_remaining and self.end_index is None and self.step == 1


@dataclass(frozen=True, slots=True)
class MetadataOption:
    name: str
    kind: MetadataOptionKind


@dataclass(frozen=True, slots=True)
class OptionScanResult:
    state: OptionScanState
    positional_indices: tuple[int, ...]
    option_index: int | None = None
    option_name: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataBind:
    selector: MetadataSelector
    kind: BindingKind | None


@dataclass(frozen=True, slots=True)
class MetadataMissingDiagnostic:
    severity: Literal['hint', 'information']
    message: str


@dataclass(frozen=True, slots=True)
class MetadataRef:
    selector: MetadataSelector
    if_missing: MetadataMissingDiagnostic | None = None


@dataclass(frozen=True, slots=True)
class MetadataCall:
    selector: MetadataSelector
    namespace: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataSource:
    selector: MetadataSelector
    base: SourceBase


@dataclass(frozen=True, slots=True)
class MetadataPackage:
    selector: MetadataSelector | None
    literal_package: str | None


@dataclass(frozen=True, slots=True)
class MetadataContext:
    body_selector: MetadataSelector
    context_name: str
    owner_selector: MetadataSelector | None


@dataclass(frozen=True, slots=True)
class MetadataProcedure:
    member_name_selector: MetadataSelector | None
    member_name_literal: str | None
    parameter_selector: MetadataSelector | None
    parameter_literal: str | None
    body_selector: MetadataSelector | None
    body_context: str | None
    parameter_plugin: MetadataPlugin | None = None


@dataclass(frozen=True, slots=True)
class MetadataPlugin:
    script_path: Path
    proc_name: str


type MetadataAnnotation = (
    MetadataBind
    | MetadataRef
    | MetadataCall
    | MetadataSource
    | MetadataPackage
    | MetadataContext
    | MetadataProcedure
    | MetadataPlugin
)


@dataclass(frozen=True, slots=True)
class MetadataCommand:
    metadata_path: Path
    uri: str
    name: str
    context_name: str | None
    context_extends: str | None
    signature: str
    documentation: str | None
    name_span: Span
    options: tuple[MetadataOption, ...]
    subcommands: tuple[str, ...]
    annotations: tuple[MetadataAnnotation, ...]
    visibility: CommandVisibility = 'public'
    alias_target: str | None = None
    is_override: bool = False
    module_name: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataAlias:
    name: str
    target: str
    uri: str
    name_span: Span
    documentation: str | None
    module_name: str
    target_module: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataFileSummary:
    modules: tuple[ModuleScope, ...]
    commands: tuple[MetadataCommand, ...]
    language_extends: tuple[tuple[str | None, str, bool], ...]
    source_paths: tuple[tuple[Path, Path], ...]
    aliases: tuple[MetadataAlias, ...]


def load_metadata_commands(
    metadata_path: MetadataPath,
    *,
    alias_paths: tuple[MetadataPath, ...] | None = None,
    revision: MetadataRevision = (),
) -> tuple[MetadataCommand, ...]:
    summary = metadata_file_summary(metadata_path, revision=revision)
    if not summary.aliases:
        return summary.commands
    if alias_paths is None:
        alias_paths = (*DEFAULT_METADATA_REGISTRY.catalog.metadata_files(), metadata_path)
    return _metadata_commands_with_aliases(metadata_path, alias_paths, revision)


@metadata_lru_cache(maxsize=128)
def _metadata_commands_with_aliases(
    metadata_path: MetadataPath, alias_paths: tuple[MetadataPath, ...], revision: MetadataRevision
) -> tuple[MetadataCommand, ...]:
    summary = metadata_file_summary(metadata_path, revision=revision)
    definitions_by_module: dict[str, dict[str, tuple[MetadataCommand, ...] | MetadataAlias]] = {}
    for candidate_path in dict.fromkeys(alias_paths):
        candidate = metadata_file_summary(candidate_path, revision=revision)
        for module in candidate.modules:
            definitions = definitions_by_module.setdefault(module.name, {})
            commands: dict[str, list[MetadataCommand]] = {}
            for command in candidate.commands:
                if command.context_name is None and command.module_name == module.name:
                    commands.setdefault(command.name, []).append(command)
            additions: dict[str, tuple[MetadataCommand, ...] | MetadataAlias] = {
                name: tuple(overloads) for name, overloads in commands.items()
            }
            additions.update(
                {
                    alias.name: alias
                    for alias in candidate.aliases
                    if alias.module_name == module.name
                }
            )
            discard_overridden_command_trees(definitions, additions)
            definitions.update(additions)

    def expand(
        module: str, alias: MetadataAlias, pending: tuple[tuple[str, str], ...]
    ) -> tuple[MetadataCommand, ...]:
        key = (module, alias.name)
        if key in pending:
            raise RuntimeError(f'Metadata alias cycle at `{module}::{alias.name}`.')
        target_module = alias.target_module or module
        definitions = definitions_by_module.get(target_module, {})
        target = definitions.get(alias.target)
        if target is None:
            raise RuntimeError(
                f'Metadata alias `{alias.name}` has unknown target `{alias.target}`.'
            )
        if isinstance(target, MetadataAlias):
            originals = expand(target_module, target, (*pending, key))
        else:
            originals = tuple(
                command
                for name, overloads in definitions.items()
                if name == alias.target or name.startswith(f'{alias.target} ')
                if not isinstance(overloads, MetadataAlias)
                for command in overloads
            )
        return tuple(
            replace(
                command,
                name=alias.name + command.name[len(alias.target) :],
                uri=alias.uri,
                name_span=alias.name_span,
                documentation=alias.documentation or command.documentation,
                alias_target=command.alias_target or command.name,
                module_name=module,
                is_override=False,
            )
            for command in originals
        )

    return summary.commands + tuple(
        command for alias in summary.aliases for command in expand(alias.module_name, alias, ())
    )


def metadata_modules(metadata_path: MetadataPath) -> tuple[ModuleScope, ...]:
    return tuple(
        dict.fromkeys(
            block.module
            for block in load_declarations(metadata_path).blocks()
            if block.module is not None
        )
    )


def metadata_file_summary(
    metadata_path: MetadataPath, *, revision: MetadataRevision = ()
) -> MetadataFileSummary:
    return _metadata_file_summary(metadata_path, revision)


def metadata_declaration_diagnostics(
    declarations: DeclarationGroup, *, span: Span
) -> tuple[Diagnostic, ...]:
    """Validate metadata in a config buffer with the same parser used for loading."""
    try:
        _summarize_declarations(declarations, config=True)
    except RuntimeError as exc:
        span = exc.span if isinstance(exc, DeclarationError) else span
        return (
            Diagnostic(
                span=span,
                message=str(exc),
                severity='error',
                code='invalid-project-config',
                source='tcl-ls',
            ),
        )
    return ()


@metadata_lru_cache(maxsize=128)
def metadata_module_names(catalog: MetadataCatalog) -> frozenset[str]:
    return frozenset(
        module.name for path in catalog.metadata_files() for module in metadata_modules(path)
    )


@metadata_lru_cache(maxsize=512)
def _metadata_file_summary(
    metadata_path: MetadataPath, _revision: MetadataRevision
) -> MetadataFileSummary:
    return _summarize_declarations(
        load_declarations(metadata_path), config=metadata_path.name == 'tcllsrc.tcl'
    )


def _summarize_declarations(group: DeclarationGroup, *, config: bool) -> MetadataFileSummary:
    try:
        summaries = tuple(
            _summarize_block(entry, config=config)
            if isinstance(entry, DeclarationBlock)
            else _summarize_declarations(entry, config=config)
            for entry in group.entries
        )
    except DeclarationError as exc:
        if group.include_site is None:
            raise
        path, span = group.include_site
        raise DeclarationError(path, span, str(exc)) from exc
    modules: dict[str, ModuleScope] = {}
    # Module declarations share a command namespace; file-scoped declarations
    # only replace commands associated with that same source file.
    definitions: dict[
        tuple[str | Path, str | None, str], tuple[MetadataCommand, ...] | MetadataAlias
    ] = {}
    extends: dict[tuple[str | None, str], bool] = {}
    sources: dict[tuple[Path, Path], None] = {}
    for summary in summaries:
        for module in summary.modules:
            previous = modules.setdefault(module.name, module)
            if previous != module:
                raise RuntimeError(f'Conflicting declarations for metadata module `{module.name}`.')
        additions: dict[
            tuple[str | Path, str | None, str], tuple[MetadataCommand, ...] | MetadataAlias
        ] = {}
        for command in summary.commands:
            scope = command.module_name or command.metadata_path
            key = (scope, command.context_name, command.name)
            current = additions.get(key, ())
            assert isinstance(current, tuple)
            additions[key] = (*current, command)
        additions.update(
            ((alias.module_name, None, alias.name), alias) for alias in summary.aliases
        )
        for scope, context, name in tuple(definitions):
            if any((scope, context, prefix) in additions for prefix in command_tree_prefixes(name)):
                del definitions[scope, context, name]
        definitions.update(additions)
        for module, name, extends_tcl in summary.language_extends:
            extends[module, name] = extends.get((module, name), False) or extends_tcl
        sources.update(dict.fromkeys(summary.source_paths))
    return MetadataFileSummary(
        modules=tuple(modules.values()),
        commands=tuple(
            command
            for entry in definitions.values()
            if isinstance(entry, tuple)
            for command in entry
        ),
        aliases=tuple(entry for entry in definitions.values() if isinstance(entry, MetadataAlias)),
        language_extends=tuple((module, name, value) for (module, name), value in extends.items()),
        source_paths=tuple(sources),
    )


def _summarize_block(block: DeclarationBlock, *, config: bool) -> MetadataFileSummary:
    module_name = None if block.module is None else block.module.name
    metadata_path = block.path
    metadata_uri = metadata_path.as_uri()
    commands: list[MetadataCommand] = []
    language_extends: list[tuple[str | None, str, bool]] = []
    source_paths: list[tuple[Path, Path]] = []
    aliases: list[MetadataAlias] = []
    for command in block.commands:
        try:
            command_name = word_static_text(command.words[0])
            if (
                config
                and module_name is None
                and command_name in {'lib-path', 'library-path', 'exclude', 'module', 'diagnostic'}
            ):
                continue
            if command_name != 'meta' or len(command.words) < 2:
                raise RuntimeError(
                    'Metadata top-level entries must be `meta` declarations or `source staticPath`.'
                )
            entry_kind = word_static_text(command.words[1])
            if entry_kind == 'alias':
                names = tuple(word_static_text(word) for word in command.words[2:])
                if (
                    len(names) not in {2, 4}
                    or any(not name or any(c.isspace() for c in name) for name in names)
                    or (len(names) == 4 and names[2] != '-module')
                ):
                    raise RuntimeError(
                        'Metadata aliases must be `meta alias name target ?-module module?` with static names.'
                    )
                if module_name is None:
                    raise RuntimeError('Metadata aliases require a module block.')
                name, target = names[:2]
                assert name is not None and target is not None
                aliases.append(
                    MetadataAlias(
                        name=normalize_command_name(name),
                        target=normalize_command_name(target),
                        uri=metadata_uri,
                        name_span=command.words[2].content_span,
                        documentation=_command_documentation(command.leading_comments),
                        module_name=module_name,
                        target_module=names[3] if len(names) == 4 else None,
                    )
                )
            elif entry_kind == 'source':
                source_path = (
                    word_static_text(command.words[2]) if len(command.words) == 3 else None
                )
                if not source_path or any(word.expanded for word in command.words):
                    raise RuntimeError('Metadata source entries must be `meta source staticPath`.')
                if module_name is not None:
                    raise RuntimeError(
                        'Metadata source entries require file-scoped metadata without a module.'
                    )
                source_paths.append(
                    (metadata_path, (metadata_path.parent / source_path).resolve(strict=False))
                )
            elif entry_kind in {'command', 'override'}:
                if entry_kind == 'override' and module_name is None:
                    raise RuntimeError('Metadata overrides require a module block.')
                commands.extend(
                    replace(entry, is_override=entry_kind == 'override', module_name=module_name)
                    for entry in _parse_metadata_command_entry(
                        command, metadata_path=metadata_path, metadata_uri=metadata_uri
                    )
                )
            elif entry_kind == 'language':
                name, extends, entries = _parse_metadata_context_entry(
                    command, metadata_path=metadata_path, metadata_uri=metadata_uri
                )
                language_extends.append((module_name, name, extends == 'tcl'))
                commands.extend(replace(entry, module_name=module_name) for entry in entries)
            else:
                raise RuntimeError(f'Unknown metadata declaration `meta {entry_kind}`.')
        except RuntimeError as exc:
            raise DeclarationError(metadata_path, command.span, str(exc)) from exc
    visibility_by_key: dict[tuple[str | None, str], CommandVisibility] = {}
    for command in commands:
        key = (command.context_name, normalize_command_name(command.name))
        if visibility_by_key.setdefault(key, command.visibility) != command.visibility:
            raise RuntimeError(f'Conflicting visibility for metadata command `{command.name}`.')
    declared_names = {command.name for command in commands if command.context_name is None}
    for alias in aliases:
        if alias.name in declared_names:
            raise RuntimeError(f'Conflicting metadata declarations for `{alias.name}`.')
        declared_names.add(alias.name)
    return MetadataFileSummary(
        modules=() if block.module is None else (block.module,),
        commands=_commands_with_derived_subcommands(tuple(commands)),
        language_extends=tuple(language_extends),
        source_paths=tuple(source_paths),
        aliases=tuple(aliases),
    )


@metadata_lru_cache(maxsize=128)
def file_scoped_metadata_sources(
    catalog: MetadataCatalog,
) -> dict[str, tuple[Path, ...]]:
    sources: dict[str, tuple[Path, ...]] = {}
    for _, metadata_files in catalog.metadata_file_layers():
        layer_sources: dict[str, list[Path]] = {}
        for metadata_path in metadata_files:
            for owner, source in metadata_file_summary(
                metadata_path, revision=catalog.revision
            ).source_paths:
                for lookup_name in metadata_lookup_names(owner):
                    layer_sources.setdefault(lookup_name, []).append(source)
        sources.update({name: tuple(dict.fromkeys(paths)) for name, paths in layer_sources.items()})
    return sources


def all_metadata_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[MetadataCommand, ...]:
    return _all_metadata_commands(metadata_registry.catalog)


@metadata_lru_cache(maxsize=1)
def _all_metadata_commands(catalog: MetadataCatalog) -> tuple[MetadataCommand, ...]:
    commands: list[MetadataCommand] = []
    for metadata_path in catalog.metadata_files():
        commands.extend(
            load_metadata_commands(
                metadata_path,
                alias_paths=catalog.metadata_files(),
                revision=catalog.revision,
            )
        )
    return tuple(commands)


def file_scoped_annotated_metadata_commands(
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> dict[tuple[str, str], MetadataCommand]:
    return _file_scoped_annotated_metadata_commands(metadata_registry.catalog)


@metadata_lru_cache(maxsize=1)
def _file_scoped_annotated_metadata_commands(
    catalog: MetadataCatalog,
) -> dict[tuple[str, str], MetadataCommand]:
    commands_by_lookup_name: dict[str, dict[str, MetadataCommand]] = {}
    for _, layer_paths in catalog.metadata_file_layers():
        layer_overrides_by_lookup_name: dict[str, dict[str, None]] = {}
        layer_commands_by_lookup_name: dict[str, dict[str, MetadataCommand]] = {}
        commands_by_owner: dict[Path, list[MetadataCommand]] = {}
        for root in layer_paths:
            for command in load_metadata_commands(
                root,
                alias_paths=catalog.metadata_files(),
                revision=catalog.revision,
            ):
                if command.module_name is None:
                    commands_by_owner.setdefault(command.metadata_path, []).append(command)
        for metadata_path, file_commands in commands_by_owner.items():
            override_names, annotated_commands = _file_scoped_annotated_entries_for_file(
                metadata_path, tuple(file_commands)
            )
            if not override_names:
                continue
            for lookup_name in metadata_lookup_names(metadata_path):
                layer_override_names = layer_overrides_by_lookup_name.setdefault(lookup_name, {})
                layer_commands = layer_commands_by_lookup_name.setdefault(lookup_name, {})
                for command_name in override_names:
                    if command_name in layer_override_names:
                        raise RuntimeError(
                            f'Conflicting file-scoped metadata annotations for '
                            f'`{command_name}` in `{metadata_path.name}`.'
                        )
                    layer_override_names[command_name] = None
                for command_name, metadata_command in annotated_commands.items():
                    existing = layer_commands.get(command_name)
                    if existing is not None and (
                        existing.options != metadata_command.options
                        or existing.subcommands != metadata_command.subcommands
                        or existing.annotations != metadata_command.annotations
                        or existing.visibility != metadata_command.visibility
                    ):
                        raise RuntimeError(
                            f'Conflicting file-scoped metadata annotations for '
                            f'`{metadata_command.name}` in `{metadata_path.name}`.'
                        )
                    layer_commands[command_name] = metadata_command

        for lookup_name, override_names in layer_overrides_by_lookup_name.items():
            commands = commands_by_lookup_name.setdefault(lookup_name, {})
            discard_overridden_command_trees(commands, override_names)
            commands.update(layer_commands_by_lookup_name.get(lookup_name, {}))

    return {
        (lookup_name, command_name): metadata_command
        for lookup_name, commands in commands_by_lookup_name.items()
        for command_name, metadata_command in commands.items()
    }


def _file_scoped_annotated_entries_for_file(
    metadata_path: Path,
    commands: tuple[MetadataCommand, ...],
) -> tuple[tuple[str, ...], dict[str, MetadataCommand]]:
    override_entries: dict[str, MetadataCommand | None] = {}
    annotated: dict[str, MetadataCommand] = {}
    for metadata_command in commands:
        if metadata_command.context_name is not None:
            continue

        command_name = normalize_command_name(metadata_command.name)
        annotated_command = (
            metadata_command
            if (
                metadata_command.options
                or metadata_command.subcommands
                or metadata_command.annotations
                or metadata_command.visibility == 'internal'
            )
            else None
        )
        existing = override_entries.get(command_name, _MISSING)
        if existing is _MISSING:
            override_entries[command_name] = annotated_command
            if annotated_command is not None:
                annotated[command_name] = annotated_command
            continue

        if annotated_command is None:
            continue
        if existing is None:
            override_entries[command_name] = annotated_command
            annotated[command_name] = annotated_command
            continue
        existing_command = cast(MetadataCommand, existing)
        if (
            existing_command.options == annotated_command.options
            and existing_command.subcommands == annotated_command.subcommands
            and existing_command.annotations == annotated_command.annotations
            and existing_command.visibility == annotated_command.visibility
        ):
            continue
        raise RuntimeError(
            f'Conflicting file-scoped metadata annotations for '
            f'`{metadata_command.name}` in `{metadata_path.name}`.'
        )

    return tuple(override_entries), annotated


def discard_overridden_command_trees[CommandValue](
    commands: dict[str, CommandValue],
    override_commands: Mapping[str, object],
) -> None:
    for existing_name in tuple(commands):
        if any(prefix in override_commands for prefix in command_tree_prefixes(existing_name)):
            commands.pop(existing_name, None)


def command_tree_prefixes(name: str) -> Iterator[str]:
    """A command and its parent commands, from most to least specific."""
    while True:
        yield name
        name, separator, _ = name.rpartition(' ')
        if not separator:
            return


def _parse_metadata_command_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    context_name: str | None = None,
    context_extends: str | None = None,
    parent_name: str | None = None,
) -> tuple[MetadataCommand, ...]:
    name_index = 2 if context_name is None and parent_name is None else 1
    words = list(command.words[name_index:])
    if len(words) < 2:
        raise RuntimeError('Metadata command entries require a name and a shape.')
    name_word = words[0]
    command_name = word_static_text(name_word)
    words = words[1:]
    visibility: CommandVisibility = 'public'
    if _is_bare_keyword(words[0], '-visibility'):
        value = word_static_text(words[1]) if len(words) > 1 else None
        if value not in {'public', 'internal'}:
            raise RuntimeError('Command visibility must be `public` or `internal`.')
        visibility = cast(CommandVisibility, value)
        words = words[2:]
    if len(words) not in {1, 2}:
        raise RuntimeError(
            'Metadata command entries must be `command name ?-visibility public|internal? '
            '{shape}` optionally followed by an annotation body, or a variants body.'
        )
    declaration_word = words[0]
    annotation_word = words[1] if len(words) == 2 else None

    if command_name is None:
        raise RuntimeError('Metadata command entries must be fully static declarations.')
    if ' ' in command_name:
        raise RuntimeError(
            'Metadata command entries must use single command names. '
            'Use nested `command name {shape}` declarations for child commands.'
        )

    full_name = command_name if parent_name is None else f'{parent_name} {command_name}'
    documentation = _command_documentation(command.leading_comments)

    if _is_bare_keyword(declaration_word, 'variants'):
        if annotation_word is None:
            raise RuntimeError(
                f'Metadata command `{full_name}` variants must be followed by a body.'
            )
        return _load_metadata_variant_commands(
            _parse_metadata_variant_body(
                annotation_word,
                metadata_uri=metadata_uri,
                command_name=full_name,
            ),
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            name_span=name_word.content_span,
            documentation=documentation,
            visibility=visibility,
        )

    if annotation_word is not None and isinstance(declaration_word, BareWord):
        raise RuntimeError(
            f'Metadata command `{full_name}` must use a braced shape when a clause body is present.'
        )

    signature = word_static_text(declaration_word)
    if signature is None:
        raise RuntimeError('Metadata command entries must be fully static declarations.')
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=full_name,
            context_name=context_name,
            context_extends=context_extends,
            signature=signature,
            documentation=documentation,
            name_span=name_word.content_span,
            options=options,
            subcommands=(),
            annotations=annotations,
            visibility=visibility,
        ),
        *nested_commands,
    )


def _parse_metadata_context_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
) -> tuple[str, str | None, tuple[MetadataCommand, ...]]:
    if len(command.words) != 4:
        raise RuntimeError('Metadata language entries must be `meta language name { ... }`.')

    context_name = word_static_text(command.words[2])
    if context_name is None:
        raise RuntimeError('Metadata language entries must have a static language name.')

    body_text = _metadata_body_text(command.words[3])
    parse_result = Parser().parse_document(
        path=f'{metadata_uri}#context:{context_name}', text=body_text
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(
            f'Invalid metadata language `{context_name}` in `{metadata_path.name}`: {message}'
        )

    nested_command_entries: list[Command] = []
    context_extends: str | None = None
    for nested_command in parse_result.script.commands:
        nested_name = word_static_text(nested_command.words[0])
        if nested_name == 'extends':
            if context_extends is not None:
                raise RuntimeError(
                    f'Metadata language `{context_name}` declares multiple extends clauses.'
                )
            if len(nested_command.words) != 2 or word_static_text(nested_command.words[1]) != 'tcl':
                raise RuntimeError(
                    f'Metadata language `{context_name}` extends clauses must be `extends tcl`.'
                )
            context_extends = 'tcl'
            continue
        if nested_name not in {'command', 'override'}:
            raise RuntimeError(
                f'Metadata language `{context_name}` entries must use '
                '`command name {args}`, `command name variants { ... }`, '
                '`override name {args}`, or `extends tcl`.'
            )
        nested_command_entries.append(nested_command)

    commands: list[MetadataCommand] = []
    for nested_command in nested_command_entries:
        commands.extend(
            replace(entry, is_override=word_static_text(nested_command.words[0]) == 'override')
            for entry in _parse_metadata_command_entry(
                nested_command,
                metadata_path=metadata_path,
                metadata_uri=metadata_uri,
                context_name=context_name,
                context_extends=context_extends,
            )
        )

    return context_name, context_extends, tuple(commands)


def select_argument_indices(
    selector: MetadataSelector,
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...] | None = None,
) -> tuple[int, ...] | None:
    expanded_flags = _normalized_argument_expansion_flags(arg_texts, arg_expanded)
    if selector.after_options:
        scan_result = scan_command_options(arg_texts, options, expanded_flags)
        if scan_result.state == 'dynamic':
            return None
        if scan_result.state not in {'ok', 'unstable'}:
            return None
        return _select_resolved_argument_indices(
            selector,
            scan_result.positional_indices,
            unstable=scan_result.state == 'unstable',
        )

    return _select_resolved_argument_indices(
        selector,
        tuple(range(len(arg_texts))),
        unstable=False,
        expanded_flags=expanded_flags,
    )


def scan_command_options(
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...] | None = None,
) -> OptionScanResult:
    expanded_flags = _normalized_argument_expansion_flags(arg_texts, arg_expanded)
    if not options:
        return _positional_scan_result(
            start_index=0,
            arg_texts=arg_texts,
            expanded_flags=expanded_flags,
            state='ok',
        )

    option_specs = {option.name: option for option in options}
    index = 0
    while index < len(arg_texts):
        if expanded_flags[index]:
            return OptionScanResult(state='unstable', positional_indices=())

        arg_text = arg_texts[index]
        if arg_text is None:
            return _positional_scan_result(
                start_index=index,
                arg_texts=arg_texts,
                expanded_flags=expanded_flags,
                state='dynamic',
            )

        option = option_specs.get(arg_text)
        if option is None:
            if arg_text.startswith('-') and arg_text != '-':
                return OptionScanResult(
                    state='unknown-option',
                    positional_indices=(),
                    option_index=index,
                    option_name=arg_text,
                )
            return _positional_scan_result(
                start_index=index,
                arg_texts=arg_texts,
                expanded_flags=expanded_flags,
                state='ok',
            )

        if option.kind == 'flag':
            index += 1
            continue
        if option.kind == 'value':
            if index + 1 >= len(arg_texts):
                return OptionScanResult(
                    state='missing-option-value',
                    positional_indices=(),
                    option_index=index,
                    option_name=arg_text,
                )
            if expanded_flags[index + 1]:
                return OptionScanResult(state='unstable', positional_indices=())
            index += 2
            continue
        return _positional_scan_result(
            start_index=index + 1,
            arg_texts=arg_texts,
            expanded_flags=expanded_flags,
            state='ok',
        )

    return OptionScanResult(state='ok', positional_indices=())


def _normalized_argument_expansion_flags(
    arg_texts: tuple[str | None, ...],
    arg_expanded: tuple[bool, ...] | None,
) -> tuple[bool, ...]:
    if arg_expanded is None:
        return (False,) * len(arg_texts)
    if len(arg_expanded) >= len(arg_texts):
        return arg_expanded[: len(arg_texts)]
    return arg_expanded + (False,) * (len(arg_texts) - len(arg_expanded))


def _positional_scan_result(
    *,
    start_index: int,
    arg_texts: tuple[str | None, ...],
    expanded_flags: tuple[bool, ...],
    state: Literal['ok', 'dynamic'],
) -> OptionScanResult:
    first_expanded_index = _first_expanded_index(expanded_flags, start_index)
    if first_expanded_index is None:
        return OptionScanResult(
            state=state,
            positional_indices=tuple(range(start_index, len(arg_texts))),
        )
    return OptionScanResult(
        state='unstable',
        positional_indices=tuple(range(start_index, first_expanded_index)),
    )


def _first_expanded_index(
    expanded_flags: tuple[bool, ...],
    start_index: int = 0,
) -> int | None:
    for index in range(start_index, len(expanded_flags)):
        if expanded_flags[index]:
            return index
    return None


def _parse_annotation_body(
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    body_text: str,
) -> tuple[tuple[MetadataOption, ...], tuple[MetadataAnnotation, ...], tuple[MetadataCommand, ...]]:
    annotation_uri = f'{metadata_uri}#{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=body_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata command annotations for `{command_name}`: {message}')

    options: list[MetadataOption] = []
    annotations: list[MetadataAnnotation] = []
    nested_commands: list[MetadataCommand] = []
    for command in parse_result.script.commands:
        annotation_name = word_static_text(command.words[0])
        if annotation_name is None:
            raise RuntimeError(
                f'Metadata command annotations for `{command_name}` must be static commands.'
            )

        if annotation_name == 'option':
            options.append(_parse_option_annotation(command, command_name))
            continue
        if annotation_name == 'command':
            nested_commands.extend(
                _parse_metadata_command_entry(
                    command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    parent_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                )
            )
            continue
        if annotation_name == 'bind':
            annotations.append(_parse_bind_annotation(command, command_name))
            continue
        if annotation_name == 'ref':
            annotations.append(_parse_ref_annotation(command, command_name))
            continue
        if annotation_name == 'call':
            words = _annotation_words(command, command_name)
            annotations.append(parse_call_value(words[1:], command_name=command_name))
            continue
        if annotation_name == 'enter':
            annotations.append(_parse_enter_annotation(command, command_name))
            continue
        if annotation_name == 'source':
            annotations.append(_parse_source_annotation(command, command_name))
            continue
        if annotation_name == 'package':
            annotations.append(_parse_package_annotation(command, command_name))
            continue
        if annotation_name == 'procedure':
            annotations.append(
                _parse_procedure_annotation(command, command_name, metadata_path=metadata_path)
            )
            continue
        if annotation_name == 'plugin':
            annotations.append(
                _parse_plugin_annotation(
                    command,
                    command_name,
                    metadata_path=metadata_path,
                )
            )
            continue
        raise RuntimeError(
            f'Unknown metadata command annotation `{annotation_name}` for `{command_name}`.'
        )

    return tuple(options), tuple(annotations), tuple(nested_commands)


def _parse_option_annotation(command: Command, command_name: str) -> MetadataOption:
    words = _annotation_words(command, command_name)
    if len(words) == 2:
        return MetadataOption(name=words[1], kind='flag')
    if len(words) == 3 and words[2] == 'value':
        return MetadataOption(name=words[1], kind='value')
    if len(words) == 3 and words[1] == '--' and words[2] == 'stop':
        return MetadataOption(name='--', kind='stop')
    raise RuntimeError(
        f'Option annotations for `{command_name}` must be `option name`, '
        '`option name value`, or `option -- stop`.'
    )


def _parse_bind_annotation(command: Command, command_name: str) -> MetadataBind:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    kind: BindingKind | None = None
    if consumed < len(words) - 1:
        if consumed != len(words) - 2:
            raise RuntimeError(
                f'Bind annotations for `{command_name}` must be '
                '`bind selector` or `bind selector kind`.'
            )
        kind = _parse_binding_kind(words[-1], command_name)
    elif _implicit_binding_kind(command_name) is None:
        raise RuntimeError(f'Metadata command `{command_name}` requires an explicit binding kind.')
    return MetadataBind(selector=selector, kind=kind)


def _parse_ref_annotation(command: Command, command_name: str) -> MetadataRef:
    words = _annotation_words(command, command_name)
    selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
    if consumed == len(words) - 1:
        return MetadataRef(selector=selector)
    if consumed != len(words) - 2:
        raise RuntimeError(
            f'Ref annotations for `{command_name}` must be `ref selector` or '
            '`ref selector {if-missing {hint|information message}}`.'
        )
    conditions = _ref_block_commands(command.words[-1], command_name)
    if len(conditions) != 1:
        raise RuntimeError(f'Ref blocks for `{command_name}` must contain one `if-missing` block.')
    condition = conditions[0]
    condition_words = _annotation_words(condition, command_name)
    if len(condition_words) != 2 or condition_words[0] != 'if-missing':
        raise RuntimeError(f'Ref blocks for `{command_name}` must contain one `if-missing` block.')
    actions = _ref_block_commands(condition.words[1], command_name)
    if len(actions) != 1:
        raise RuntimeError(f'If-missing blocks for `{command_name}` need one diagnostic action.')
    action = _annotation_words(actions[0], command_name)
    if len(action) != 2 or action[0] not in {'hint', 'information'} or not action[1].strip():
        raise RuntimeError(
            f'If-missing actions for `{command_name}` must be `hint message` or '
            '`information message`, with a nonempty static message.'
        )
    return MetadataRef(
        selector=selector,
        if_missing=MetadataMissingDiagnostic(
            cast(Literal['hint', 'information'], action[0]), action[1]
        ),
    )


def _ref_block_commands(word: Word, command_name: str) -> tuple[Command, ...]:
    if not isinstance(word, BracedWord) or word.expanded:
        raise RuntimeError(f'Ref and if-missing bodies for `{command_name}` must be braced blocks.')
    parsed = Parser().parse_document(f'metadata:{command_name}', word.raw_text[1:-1])
    if parsed.diagnostics:
        raise RuntimeError(f'Invalid ref or if-missing block for `{command_name}`.')
    return parsed.script.commands


def parse_call_value(words: list[str] | tuple[str, ...], *, command_name: str) -> MetadataCall:
    selector, consumed = _parse_selector_tokens(words, command_name=command_name)
    if selector.list_mode or selector.step != 1:
        raise RuntimeError(
            f'Call annotations for `{command_name}` must select contiguous argument words.'
        )
    namespace: str | None = None
    if consumed != len(words):
        if len(words) - consumed != 2 or words[consumed] != 'namespace':
            raise RuntimeError(
                f'Call annotations for `{command_name}` must be '
                '`call selector ?namespace absoluteName?`.'
            )
        namespace = words[-1]
        if not namespace.startswith('::') or any(character.isspace() for character in namespace):
            raise RuntimeError(
                f'Call namespaces for `{command_name}` must be absolute Tcl namespace names.'
            )
        namespace = qualify_namespace(namespace, '::')
    return MetadataCall(selector=selector, namespace=namespace)


def _parse_source_annotation(command: Command, command_name: str) -> MetadataSource:
    words = _annotation_words(command, command_name)
    if len(words) < 3:
        raise RuntimeError(
            f'Source annotations for `{command_name}` must be `source selector base`.'
        )
    selector, consumed = _parse_selector_tokens(words[1:-1], command_name=command_name)
    if consumed != len(words) - 2:
        raise RuntimeError(
            f'Source annotations for `{command_name}` must be `source selector base`.'
        )
    return MetadataSource(selector=selector, base=_parse_source_base(words[-1]))


def _parse_package_annotation(command: Command, command_name: str) -> MetadataPackage:
    return parse_package_value(
        _annotation_words(command, command_name)[1:], command_name=command_name
    )


def parse_package_value(
    words: list[str] | tuple[str, ...], *, command_name: str
) -> MetadataPackage:
    settings = parse_metadata_settings(
        words, command_name=command_name, role='package', keys={'select', 'literal'}
    )
    words = _source_setting_words(settings, command_name=command_name, role='package')
    if len(words) == 2 and words[0] == 'literal':
        return MetadataPackage(selector=None, literal_package=words[1])
    if len(words) >= 2 and words[0] == 'select':
        selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
        if consumed != len(words) - 1:
            raise RuntimeError(
                f'Package annotations for `{command_name}` must be `package {{literal name}}` '
                'or `package {select selector}`.'
            )
        _validate_package_selector(selector, command_name)
        return MetadataPackage(selector=selector, literal_package=None)
    raise RuntimeError(
        f'Package annotations for `{command_name}` must be `package {{literal name}}` '
        'or `package {select selector}`.'
    )


def _parse_enter_annotation(command: Command, command_name: str) -> MetadataContext:
    words = _annotation_words(command, command_name)
    if len(words) < 4 or words[2] != 'body':
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must be '
            '`enter language body selector` or '
            '`enter language body selector owner selector`.'
        )

    context_name = words[1]
    body_selector, consumed = _parse_selector_tokens(words[3:], command_name=command_name)
    owner_selector: MetadataSelector | None = None
    index = 3 + consumed
    if index < len(words):
        if words[index] != 'owner':
            raise RuntimeError(
                f'Enter annotations for `{command_name}` must be '
                '`enter language body selector` or '
                '`enter language body selector owner selector`.'
            )
        owner_selector, owner_consumed = _parse_selector_tokens(
            words[index + 1 :],
            command_name=command_name,
        )
        if owner_consumed != len(words) - index - 1:
            raise RuntimeError(
                f'Enter annotations for `{command_name}` must be '
                '`enter language body selector` or '
                '`enter language body selector owner selector`.'
            )
        _validate_context_owner_selector(owner_selector, command_name)
    _validate_context_body_selector(body_selector, command_name)
    return MetadataContext(
        body_selector=body_selector,
        context_name=context_name,
        owner_selector=owner_selector,
    )


def _parse_procedure_annotation(
    command: Command, command_name: str, *, metadata_path: Path
) -> MetadataProcedure:
    if len(command.words) != 2:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must be '
            'a `procedure { ... }` block with `name ...` and `params ...`, '
            'plus optional `body {select selector}` and `language body-language`.'
        )

    config_text = _metadata_body_text(command.words[1])
    annotation_uri = f'procedure:{command_name}'
    parse_result = Parser().parse_document(path=annotation_uri, text=config_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid procedure annotation for `{command_name}`: {message}')

    member_name_selector: MetadataSelector | object | None = _MISSING
    member_name_literal: str | object | None = _MISSING
    parameter_selector: MetadataSelector | object | None = _MISSING
    parameter_literal: str | object | None = _MISSING
    body_selector: MetadataSelector | None = None
    body_context: str | None = None
    parameter_plugin: MetadataPlugin | None = None

    for nested_command in parse_result.script.commands:
        nested_words = _annotation_words(nested_command, command_name)
        nested_name = nested_words[0]
        if nested_name == 'name':
            if member_name_selector is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `name`.'
                )
            member_name_selector, member_name_literal = parse_procedure_value(
                nested_words[1:],
                command_name=command_name,
                role='name',
                allow_literal=True,
                allow_none=True,
            )
            continue
        if nested_name == 'params':
            if parameter_selector is not _MISSING:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `params`.'
                )
            (
                parameter_selector,
                parameter_literal,
                parameter_plugin,
            ) = _parse_procedure_parameter_annotation(
                nested_words[1:],
                command_name=command_name,
                metadata_path=metadata_path,
            )
            continue
        if nested_name == 'body':
            if body_selector is not None:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `body`.'
                )
            body_selector, body_literal = parse_procedure_value(
                nested_words[1:],
                command_name=command_name,
                role='body',
                allow_literal=False,
                allow_none=False,
            )
            if body_literal is not None:
                raise RuntimeError(
                    f'Procedure body selectors for `{command_name}` must use `body {{select selector}}`.'
                )
            continue
        if nested_name == 'language':
            if body_context is not None:
                raise RuntimeError(
                    f'Procedure annotations for `{command_name}` may only declare one `language`.'
                )
            if len(nested_words) != 2:
                raise RuntimeError(
                    f'Procedure body languages for `{command_name}` must be `language name`.'
                )
            body_context = nested_words[1]
            continue
        raise RuntimeError(f'Unknown procedure setting `{nested_name}` for `{command_name}`.')

    if member_name_selector is _MISSING or parameter_selector is _MISSING:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` must declare `name` and `params`.'
        )
    if body_context is not None and body_selector is None:
        raise RuntimeError(
            f'Procedure annotations for `{command_name}` may only declare `language` '
            'when `body` is present.'
        )

    return MetadataProcedure(
        member_name_selector=cast(MetadataSelector | None, member_name_selector),
        member_name_literal=cast(str | None, member_name_literal),
        parameter_selector=cast(MetadataSelector | None, parameter_selector),
        parameter_literal=cast(str | None, parameter_literal),
        body_selector=body_selector,
        body_context=body_context,
        parameter_plugin=parameter_plugin,
    )


def _parse_procedure_parameter_annotation(
    words: list[str], *, command_name: str, metadata_path: Path
) -> tuple[MetadataSelector | None, str | None, MetadataPlugin | None]:
    selector, literal, plugin_words = parse_procedure_parameter_settings(
        words, command_name=command_name
    )
    if plugin_words is None:
        return selector, literal, None
    plugin = _metadata_plugin(
        plugin_words[0],
        plugin_words[1],
        command_name=command_name,
        metadata_path=metadata_path,
    )
    return selector, literal, plugin


def parse_procedure_parameter_settings(
    words: list[str] | tuple[str, ...], *, command_name: str, allow_plugin: bool = True
) -> tuple[MetadataSelector | None, str | None, tuple[str, str] | None]:
    keys = {'select', 'literal'}
    if allow_plugin:
        keys.add('plugin')
    settings = parse_metadata_settings(
        words,
        command_name=command_name,
        role='procedure parameter',
        keys=keys,
    )
    plugin_value = settings.pop('plugin', None)
    selector, literal = _parse_procedure_settings(
        settings, command_name=command_name, role='params', allow_literal=True, allow_none=True
    )
    if plugin_value is None:
        return selector, literal, None
    if selector is None:
        raise RuntimeError(f'Parameter plugins for `{command_name}` require `select`.')
    try:
        plugin_words = split_tcl_list(
            plugin_value, Position(offset=0, line=0, character=0), strict=True
        )
    except ValueError as error:
        raise RuntimeError(f'Invalid parameter plugin for `{command_name}`: {error}') from error
    if len(plugin_words) != 2:
        raise RuntimeError(
            f'Parameter plugins for `{command_name}` must use `plugin {{scriptPath procName}}`.'
        )
    return selector, literal, (plugin_words[0].text, plugin_words[1].text)


def parse_procedure_parameters(
    words: list[str] | tuple[str, ...], *, command_name: str
) -> tuple[MetadataSelector | None, str | None]:
    selector, literal, _ = parse_procedure_parameter_settings(
        words, command_name=command_name, allow_plugin=False
    )
    return selector, literal


def parse_metadata_settings(
    words: list[str] | tuple[str, ...], *, command_name: str, role: str, keys: set[str]
) -> dict[str, str]:
    if len(words) != 1:
        raise RuntimeError(
            f'Metadata {role} settings for `{command_name}` must use one braced key/value list.'
        )
    try:
        items = split_tcl_list(words[0], Position(offset=0, line=0, character=0), strict=True)
    except ValueError as error:
        raise RuntimeError(f'Invalid {role} list for `{command_name}`: {error}') from error

    if len(items) % 2:
        raise RuntimeError(
            f'Metadata {role} settings for `{command_name}` must contain key/value pairs.'
        )

    settings: dict[str, str] = {}
    for key, value in zip(items[::2], items[1::2], strict=True):
        if key.text not in keys:
            raise RuntimeError(f'Unknown {role} setting `{key.text}`.')
        if key.text in settings:
            raise RuntimeError(
                f'Metadata {role} settings may only declare one `{key.text}` setting.'
            )
        settings[key.text] = value.text
    return settings


def _source_setting_words(settings: dict[str, str], *, command_name: str, role: str) -> list[str]:
    if ('select' in settings) == ('literal' in settings):
        raise RuntimeError(
            f'Metadata {role} settings must declare exactly one of `select` or `literal`.'
        )
    if 'literal' in settings:
        return ['literal', settings['literal']]

    try:
        selector_items = split_tcl_list(
            settings['select'], Position(offset=0, line=0, character=0), strict=True
        )
    except ValueError as error:
        raise RuntimeError(
            f'Invalid metadata {role} selector for `{command_name}`: {error}'
        ) from error
    return ['select', *(item.text for item in selector_items)]


def _parse_plugin_annotation(
    command: Command,
    command_name: str,
    *,
    metadata_path: Path,
) -> MetadataPlugin:
    words = _annotation_words(command, command_name)
    if len(words) != 3:
        raise RuntimeError(
            f'Plugin annotations for `{command_name}` must be `plugin scriptPath procName`.'
        )

    return _metadata_plugin(
        words[1], words[2], command_name=command_name, metadata_path=metadata_path
    )


def _metadata_plugin(
    script: str, proc_name: str, *, command_name: str, metadata_path: Path
) -> MetadataPlugin:
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = metadata_path.parent / script_path
    script_path = script_path.resolve(strict=False)
    if not script_path.is_file():
        raise RuntimeError(
            f'Plugin annotation for `{command_name}` references missing script `{script}`.'
        )

    return MetadataPlugin(script_path=script_path, proc_name=proc_name)


def _validate_package_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or not selector.selects_single_argument:
        raise RuntimeError(
            f'Package annotations for `{command_name}` must select a single argument.'
        )


def _validate_context_body_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must use direct positional selectors.'
        )
    if selector.step != 1:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must select one contiguous body range.'
        )


def _validate_context_owner_selector(selector: MetadataSelector, command_name: str) -> None:
    if selector.list_mode or selector.after_options or not selector.selects_single_argument:
        raise RuntimeError(
            f'Enter annotations for `{command_name}` must select exactly one owner argument.'
        )


def _parse_selector_tokens(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
) -> tuple[MetadataSelector, int]:
    index = 0
    after_options = False
    list_mode = False
    step = 1

    if index < len(words) and words[index] == 'after-options':
        after_options = True
        index += 1
    if index < len(words) and words[index] == 'list':
        list_mode = True
        index += 1
    if index >= len(words):
        raise RuntimeError(f'Metadata selector for `{command_name}` is missing an index.')

    start_index, start_from_end, all_remaining, end_index, end_from_end = _parse_selector_range(
        words[index],
        command_name=command_name,
    )
    index += 1

    if index < len(words) and words[index] == 'step':
        if index + 1 >= len(words):
            raise RuntimeError(f'Metadata selector for `{command_name}` must be `selector step N`.')
        step_text = words[index + 1]
        if not step_text.isdigit() or step_text == '0':
            raise RuntimeError(f'Metadata selector for `{command_name}` must use a positive step.')
        step = int(step_text)
        index += 2

    if step != 1 and not (all_remaining or end_index is not None):
        raise RuntimeError(
            f'Metadata selector for `{command_name}` requires a range before `step`.'
        )

    return (
        MetadataSelector(
            start_index=start_index,
            all_remaining=all_remaining,
            list_mode=list_mode,
            after_options=after_options,
            step=step,
            start_from_end=start_from_end,
            end_index=end_index,
            end_from_end=end_from_end,
        ),
        index,
    )


def parse_selector_tokens(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
) -> tuple[MetadataSelector, int]:
    return _parse_selector_tokens(words, command_name=command_name)


def validate_context_body_selector(selector: MetadataSelector, command_name: str) -> None:
    _validate_context_body_selector(selector, command_name)


def validate_context_owner_selector(selector: MetadataSelector, command_name: str) -> None:
    _validate_context_owner_selector(selector, command_name)


def validate_procedure_selector(
    selector: MetadataSelector,
    *,
    command_name: str,
    role: str,
) -> None:
    _validate_procedure_selector(selector, command_name=command_name, role=role)


def _select_resolved_argument_indices(
    selector: MetadataSelector,
    resolved_indices: tuple[int, ...],
    *,
    unstable: bool,
    expanded_flags: tuple[bool, ...] | None = None,
) -> tuple[int, ...] | None:
    if not resolved_indices and unstable:
        return None

    effective_end = _effective_selector_end(selector, len(resolved_indices))
    if effective_end is None:
        if unstable:
            return None
    else:
        if unstable and effective_end >= len(resolved_indices):
            return None
        if expanded_flags is not None and _selector_is_unstable(
            selector,
            expanded_flags=expanded_flags,
            resolved_count=len(resolved_indices),
            effective_end=effective_end,
        ):
            return None

    start_index = _resolve_selector_endpoint(
        selector.start_index,
        from_end=selector.start_from_end,
        resolved_count=len(resolved_indices),
    )
    if start_index < 0:
        start_index = 0
    if start_index >= len(resolved_indices):
        if unstable:
            return None
        return ()

    if effective_end is None:
        stop_index = len(resolved_indices) - 1
    else:
        stop_index = min(effective_end, len(resolved_indices) - 1)

    if stop_index < start_index:
        return ()

    return tuple(
        resolved_indices[index] for index in range(start_index, stop_index + 1, selector.step)
    )


def _selector_is_unstable(
    selector: MetadataSelector,
    *,
    expanded_flags: tuple[bool, ...],
    resolved_count: int,
    effective_end: int | None,
) -> bool:
    first_expanded_index = _first_expanded_index(expanded_flags)
    if first_expanded_index is None:
        return False
    if selector.has_relative_bounds or selector.all_remaining:
        return True
    assert effective_end is not None
    return first_expanded_index <= effective_end


def _effective_selector_end(selector: MetadataSelector, resolved_count: int) -> int | None:
    if selector.all_remaining:
        return None
    if selector.end_index is None:
        return _resolve_selector_endpoint(
            selector.start_index,
            from_end=selector.start_from_end,
            resolved_count=resolved_count,
        )
    return _resolve_selector_endpoint(
        selector.end_index,
        from_end=selector.end_from_end,
        resolved_count=resolved_count,
    )


def _resolve_selector_endpoint(
    index: int,
    *,
    from_end: bool,
    resolved_count: int,
) -> int:
    if from_end:
        return resolved_count - 1 - index
    return index


def _parse_selector_range(
    token: str,
    *,
    command_name: str,
) -> tuple[int, bool, bool, int | None, bool]:
    if '..' not in token:
        start_index, start_from_end = _parse_selector_endpoint(token, command_name=command_name)
        return start_index, start_from_end, False, None, False

    start_text, end_text = token.split('..', maxsplit=1)
    start_index, start_from_end = _parse_selector_endpoint(start_text, command_name=command_name)
    if end_text == '':
        return start_index, start_from_end, True, None, False

    end_index, end_from_end = _parse_selector_endpoint(end_text, command_name=command_name)
    return start_index, start_from_end, False, end_index, end_from_end


def _parse_selector_endpoint(
    text: str,
    *,
    command_name: str,
) -> tuple[int, bool]:
    if text == '':
        raise RuntimeError(f'Metadata selector for `{command_name}` is missing an index.')
    if text == 'last':
        return 0, True
    if text.startswith('last-'):
        offset_text = text.removeprefix('last-')
        if not offset_text.isdigit() or offset_text == '0':
            raise RuntimeError(
                f'Metadata selector for `{command_name}` must use `last` or `last-N` '
                'with a positive integer.'
            )
        return int(offset_text), True
    if not text.isdigit() or text == '0':
        raise RuntimeError(
            f'Metadata selector for `{command_name}` must use a positive 1-based index, '
            '`last`, or `last-N`.'
        )
    return int(text) - 1, False


def _parse_source_base(text: str) -> SourceBase:
    if text == 'caller':
        return 'caller'
    if text == 'definition':
        return 'definition'
    raise RuntimeError(f'Unknown metadata source base `{text}`.')


def _parse_binding_kind(text: str, command_name: str) -> BindingKind:
    if text not in BINDING_KINDS:
        raise RuntimeError(f'Unknown metadata binding kind `{text}` for `{command_name}`.')
    return text


def _implicit_binding_kind(command_name: str) -> BindingKind | None:
    inferred_kind = command_name.rsplit(' ', maxsplit=1)[-1].rsplit('::', maxsplit=1)[-1]
    if inferred_kind not in BINDING_KINDS:
        return None
    return inferred_kind


def parse_procedure_value(
    words: list[str] | tuple[str, ...],
    *,
    command_name: str,
    role: str,
    allow_literal: bool,
    allow_none: bool,
) -> tuple[MetadataSelector | None, str | None]:
    settings = parse_metadata_settings(
        words, command_name=command_name, role=f'procedure {role}', keys={'select', 'literal'}
    )
    return _parse_procedure_settings(
        settings,
        command_name=command_name,
        role=role,
        allow_literal=allow_literal,
        allow_none=allow_none,
    )


def _parse_procedure_settings(
    settings: dict[str, str],
    *,
    command_name: str,
    role: str,
    allow_literal: bool,
    allow_none: bool,
) -> tuple[MetadataSelector | None, str | None]:
    if not settings:
        if not allow_none:
            raise RuntimeError(
                f'Procedure {role} settings for `{command_name}` do not support empty settings.'
            )
        return None, None

    words = _source_setting_words(settings, command_name=command_name, role=role)
    if len(words) >= 2 and words[0] == 'select':
        selector, consumed = _parse_selector_tokens(words[1:], command_name=command_name)
        if consumed != len(words) - 1:
            raise RuntimeError(
                f'Procedure {role} settings for `{command_name}` must use '
                f'`{role} {{select selector}}`.'
            )
        _validate_procedure_selector(selector, command_name=command_name, role=role)
        return selector, None

    if allow_literal and len(words) == 2 and words[0] == 'literal':
        return None, words[1]

    forms = [f'`{role} {{select selector}}`']
    if allow_literal:
        forms.append(f'`{role} {{literal value}}`')
    if allow_none:
        forms.append(f'`{role} {{}}`')
    raise RuntimeError(
        f'Procedure {role} settings for `{command_name}` must be ' + ' or '.join(forms) + '.'
    )


def _validate_procedure_selector(
    selector: MetadataSelector,
    *,
    command_name: str,
    role: str,
) -> None:
    if selector.list_mode or not selector.selects_single_argument:
        raise RuntimeError(
            f'Procedure {role} selectors for `{command_name}` must select exactly one argument.'
        )


def _parse_metadata_form_entry(
    command: Command,
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    name_span: Span,
    documentation: str | None,
    visibility: CommandVisibility,
) -> tuple[MetadataCommand, ...]:
    if len(command.words) not in {2, 3}:
        raise RuntimeError(
            f'Form entries for `{command_name}` must be `form {{shape}}` optionally '
            'followed by a clause body.'
        )

    signature = word_static_text(command.words[1])
    if signature is None:
        raise RuntimeError(f'Form entries for `{command_name}` must be fully static.')

    annotation_word = command.words[2] if len(command.words) == 3 else None
    options: tuple[MetadataOption, ...] = ()
    annotations: tuple[MetadataAnnotation, ...] = ()
    nested_commands: tuple[MetadataCommand, ...] = ()
    if annotation_word is not None:
        options, annotations, nested_commands = _parse_annotation_body(
            metadata_path=metadata_path,
            metadata_uri=metadata_uri,
            command_name=command_name,
            context_name=context_name,
            context_extends=context_extends,
            body_text=_metadata_body_text(annotation_word),
        )

    return (
        MetadataCommand(
            metadata_path=metadata_path,
            uri=metadata_uri,
            name=command_name,
            context_name=context_name,
            context_extends=context_extends,
            signature=signature,
            documentation=_command_documentation(command.leading_comments) or documentation,
            name_span=name_span,
            options=options,
            subcommands=(),
            annotations=annotations,
            visibility=visibility,
        ),
        *nested_commands,
    )


def _parse_metadata_variant_body(
    word: Word,
    *,
    metadata_uri: str,
    command_name: str,
) -> tuple[Command, ...]:
    body_text = _metadata_body_text(word)
    parse_result = Parser().parse_document(
        path=f'{metadata_uri}#{command_name}:variants', text=body_text
    )
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid metadata variants for `{command_name}`: {message}')
    if not parse_result.script.commands:
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies must contain '
            '`form` or `command` entries.'
        )
    return parse_result.script.commands


def _load_metadata_variant_commands(
    commands: tuple[Command, ...],
    *,
    metadata_path: Path,
    metadata_uri: str,
    command_name: str,
    context_name: str | None,
    context_extends: str | None,
    name_span: Span,
    documentation: str | None,
    visibility: CommandVisibility,
) -> tuple[MetadataCommand, ...]:
    loaded_commands: list[MetadataCommand] = []
    saw_form = False
    for nested_command in commands:
        nested_name = word_static_text(nested_command.words[0])
        if nested_name == 'form':
            saw_form = True
            loaded_commands.extend(
                _parse_metadata_form_entry(
                    nested_command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    command_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                    name_span=name_span,
                    documentation=documentation,
                    visibility=visibility,
                )
            )
            continue
        if nested_name == 'command':
            loaded_commands.extend(
                _parse_metadata_command_entry(
                    nested_command,
                    metadata_path=metadata_path,
                    metadata_uri=metadata_uri,
                    parent_name=command_name,
                    context_name=context_name,
                    context_extends=context_extends,
                )
            )
            continue
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies may only contain '
            '`form` and `command` entries.'
        )
    if not saw_form:
        raise RuntimeError(
            f'Metadata command `{command_name}` variants bodies must declare '
            'at least one `form` entry.'
        )
    return tuple(loaded_commands)


def _annotation_words(command: Command, command_name: str) -> list[str]:
    words: list[str] = []
    for word in command.words:
        static_text = word_static_text(word)
        if static_text is None:
            raise RuntimeError(
                f'Metadata command annotations for `{command_name}` must be fully static.'
            )
        words.append(static_text)
    return words


def _commands_with_derived_subcommands(
    commands: tuple[MetadataCommand, ...],
) -> tuple[MetadataCommand, ...]:
    child_values_by_key: dict[tuple[str | None, str], dict[str, None]] = {}
    # Each name supplies the next subcommand for each of its prefixes.
    for command in commands:
        for index, character in enumerate(command.name):
            if character != ' ' or index + 1 == len(command.name):
                continue
            key = (command.context_name, command.name[:index])
            child = command.name[index + 1 :].split(' ', maxsplit=1)[0]
            child_values_by_key.setdefault(key, {}).setdefault(child, None)

    if not child_values_by_key:
        return commands

    derived_commands: list[MetadataCommand] = []
    for command in commands:
        derived_values = child_values_by_key.get((command.context_name, command.name))
        if derived_values is None:
            derived_commands.append(command)
            continue

        subcommands = _merge_subcommands(command.subcommands, tuple(derived_values))

        derived_commands.append(replace(command, subcommands=subcommands))

    return tuple(derived_commands)


def _merge_subcommands(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: dict[str, None] = {}
    for group in groups:
        for value in group:
            merged.setdefault(value, None)
    return tuple(merged)


def _metadata_body_text(word: Word) -> str:
    if isinstance(word, BracedWord) and not word.expanded:
        raw_text = word.raw_text
        if raw_text.startswith('{'):
            raw_text = raw_text[1:]
        if raw_text.endswith('}'):
            raw_text = raw_text[:-1]
        return raw_text

    text = word_static_text(word)
    if text is None:
        raise RuntimeError('Metadata command annotation bodies must be static words.')
    return text


def _is_bare_keyword(word: Word, keyword: str) -> bool:
    return isinstance(word, BareWord) and word_static_text(word) == keyword


def _command_documentation(comments: tuple[Token, ...]) -> str | None:
    if not comments:
        return None

    lines = [_comment_text(comment.text) for comment in comments]
    documentation = '\n'.join(lines).strip()
    return documentation or None


def _comment_text(text: str) -> str:
    if not text.startswith('#'):
        return text
    text = text[1:]
    return text[1:] if text.startswith(' ') else text
