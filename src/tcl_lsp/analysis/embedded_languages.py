from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from tcl_lsp.analysis.arity import metadata_signature_arity
from tcl_lsp.analysis.facts.utils import namespace_for_name, normalize_command_name, qualify_name
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataCommand,
    MetadataContext,
    MetadataProcedure,
    all_metadata_language_extends,
    load_metadata_commands,
    scan_command_options,
    select_argument_indices,
)
from tcl_lsp.analysis.signature_matching import metadata_signature_match_state
from tcl_lsp.cache import metadata_lru_cache
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY, MetadataRegistry
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import BareWord, Command, Word

type EmbeddedLanguageName = str


@dataclass(frozen=True, slots=True)
class EmbeddedLanguageEntry:
    language: EmbeddedLanguageName
    owner_name: str | None
    namespace: str
    script_word_index: int | None
    inline_command_start_index: int | None
    inline_command_end_index: int | None


@dataclass(frozen=True, slots=True)
class MatchedEmbeddedCommand:
    metadata_command: MetadataCommand
    prefix_word_count: int


@dataclass(frozen=True, slots=True)
class ContextualCommand:
    language: EmbeddedLanguageName
    name: str
    overloads: tuple[MetadataCommand, ...]


@dataclass(frozen=True, slots=True)
class _EmbeddedLanguage:
    name: EmbeddedLanguageName
    commands_by_name: dict[str, tuple[MetadataCommand, ...]]
    root_commands: frozenset[str]
    procedure_roots: frozenset[str]
    binding_roots: frozenset[str]
    extends_tcl: bool


@metadata_lru_cache(maxsize=1)
def _embedded_languages(
    metadata_registry: MetadataRegistry,
) -> dict[EmbeddedLanguageName, _EmbeddedLanguage]:
    commands_by_language = _embedded_language_command_index(metadata_registry)
    extends_tcl_by_language = all_metadata_language_extends(metadata_registry).copy()

    # Keep declared languages even when they contribute no commands so closed
    # DSLs do not silently reopen as plain Tcl.
    for language_name in extends_tcl_by_language:
        commands_by_language.setdefault(language_name, {})

    embedded_languages: dict[str, _EmbeddedLanguage] = {}
    for language_name, commands_for_language in commands_by_language.items():
        root_commands: set[str] = set()
        procedure_roots: set[str] = set()
        binding_roots: set[str] = set()
        for command_name, overloads in commands_for_language.items():
            root_name = _root_command_name(command_name)
            root_commands.add(root_name)
            if any(
                isinstance(annotation, MetadataProcedure)
                for overload in overloads
                for annotation in overload.annotations
            ):
                procedure_roots.add(root_name)
            if any(
                isinstance(annotation, MetadataBind)
                for overload in overloads
                for annotation in overload.annotations
            ):
                binding_roots.add(root_name)

        embedded_languages[language_name] = _EmbeddedLanguage(
            name=language_name,
            commands_by_name=commands_for_language,
            root_commands=frozenset(root_commands),
            procedure_roots=frozenset(procedure_roots),
            binding_roots=frozenset(binding_roots),
            extends_tcl=extends_tcl_by_language.get(language_name, False),
        )
    return embedded_languages


@metadata_lru_cache(maxsize=1)
def _context_entry_command_index(
    metadata_registry: MetadataRegistry,
) -> dict[str, tuple[MetadataCommand, ...]]:
    commands_by_name: dict[str, tuple[MetadataCommand, ...]] = {}
    for layer_commands in _metadata_commands_by_layer(metadata_registry):
        layer_commands_by_name: dict[str, list[MetadataCommand]] = {}
        for metadata_command in layer_commands:
            if metadata_command.context_name is not None:
                continue
            layer_commands_by_name.setdefault(metadata_command.name, []).append(metadata_command)

        _discard_overridden_command_trees(commands_by_name, layer_commands_by_name)
        commands_by_name.update(
            {
                command_name: tuple(overloads)
                for command_name, overloads in layer_commands_by_name.items()
            }
        )

    return {
        command_name: overloads
        for command_name, overloads in commands_by_name.items()
        if any(
            isinstance(annotation, MetadataContext)
            for overload in overloads
            for annotation in overload.annotations
        )
    }


@metadata_lru_cache(maxsize=1)
def _embedded_language_command_index(
    metadata_registry: MetadataRegistry,
) -> dict[str, dict[str, tuple[MetadataCommand, ...]]]:
    commands_by_language: dict[str, dict[str, tuple[MetadataCommand, ...]]] = {}
    for layer_commands in _metadata_commands_by_layer(metadata_registry):
        layer_commands_by_language: dict[str, dict[str, list[MetadataCommand]]] = {}
        for metadata_command in layer_commands:
            if metadata_command.context_name is None:
                continue
            layer_commands_by_language.setdefault(metadata_command.context_name, {}).setdefault(
                metadata_command.name, []
            ).append(metadata_command)

        for language_name, layer_commands_by_name in layer_commands_by_language.items():
            commands_for_language = commands_by_language.setdefault(language_name, {})
            _discard_overridden_command_trees(commands_for_language, layer_commands_by_name)
            commands_for_language.update(
                {
                    command_name: tuple(overloads)
                    for command_name, overloads in layer_commands_by_name.items()
                }
            )
    return commands_by_language


@metadata_lru_cache(maxsize=1)
def _metadata_commands_by_layer(
    metadata_registry: MetadataRegistry,
) -> tuple[tuple[MetadataCommand, ...], ...]:
    layer_commands: list[tuple[MetadataCommand, ...]] = []
    for _, layer_paths in metadata_registry.metadata_file_layers():
        commands: list[MetadataCommand] = []
        for metadata_path in layer_paths:
            commands.extend(load_metadata_commands(metadata_path))
        if commands:
            layer_commands.append(tuple(commands))
    return tuple(layer_commands)


def _discard_overridden_command_trees(
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


def match_embedded_language_command(
    command: Command,
    language_name: EmbeddedLanguageName | None,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> MatchedEmbeddedCommand | None:
    language = _embedded_languages(metadata_registry).get(language_name or '')
    if language is None:
        return None
    return _match_metadata_command(command, language.commands_by_name)


def contextual_command_target(
    language_name: EmbeddedLanguageName | None,
    command_name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> ContextualCommand | None:
    language = _embedded_languages(metadata_registry).get(language_name or '')
    if language is None:
        return None

    overloads = language.commands_by_name.get(command_name)
    if overloads is None:
        return None
    return ContextualCommand(language=language.name, name=command_name, overloads=overloads)


def contextual_language_allows_tcl_fallback(
    language_name: EmbeddedLanguageName | None,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> bool:
    if language_name is None or language_name == 'tcl':
        return True

    language = _embedded_languages(metadata_registry).get(language_name or '')
    if language is None:
        return False
    return language.extends_tcl


def resolves_contextual_command(
    language_name: EmbeddedLanguageName | None,
    command_name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> bool:
    return (
        contextual_command_target(
            language_name,
            command_name,
            metadata_registry=metadata_registry,
        )
        is not None
    )


def match_embedded_language_entries(
    command: Command,
    *,
    current_namespace: str,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[EmbeddedLanguageEntry, ...] | None:
    matched = _match_metadata_command(
        command,
        _context_entry_command_index(metadata_registry),
    )
    if matched is None:
        return ()

    entries: dict[EmbeddedLanguageEntry, None] = {}
    for annotation in matched.metadata_command.annotations:
        if not isinstance(annotation, MetadataContext):
            continue
        entry = embedded_language_entry_for_annotation(
            command,
            metadata_command=matched.metadata_command,
            annotation=annotation,
            prefix_word_count=matched.prefix_word_count,
            current_namespace=current_namespace,
        )
        if entry is None:
            continue
        entries.setdefault(entry, None)

    return resolve_embedded_language_entries(entries)


def resolve_embedded_language_entries(
    entries: Iterable[EmbeddedLanguageEntry],
) -> tuple[EmbeddedLanguageEntry, ...] | None:
    ordered_entries = tuple(
        sorted(
            dict.fromkeys(entries),
            key=lambda entry: (
                _entry_start_index(entry),
                _entry_end_index(entry),
                entry.language,
                entry.namespace,
                entry.owner_name or '',
            ),
        )
    )

    # Overlapping selections are ambiguous even when they mention the same
    # language, because one word range cannot belong to two embedded parses.
    for left, right in pairwise(ordered_entries):
        if _entries_overlap(left, right):
            return None
    return ordered_entries


def contextual_resolution_reason(
    language_name: EmbeddedLanguageName | None,
    command_name: str,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> str:
    language = _embedded_languages(metadata_registry).get(language_name or '')
    if language is None:
        return 'Resolved in an embedded language context.'

    normalized_name = normalize_command_name(command_name)
    if normalized_name in language.procedure_roots:
        return 'Resolved as a procedure-like command in an embedded language context.'
    if normalized_name in language.binding_roots:
        return 'Resolved as a contextual command with local variable effects.'
    return 'Resolved as a contextual command in an embedded language context.'


def _match_metadata_command(
    command: Command,
    commands_by_name: dict[str, tuple[MetadataCommand, ...]],
) -> MatchedEmbeddedCommand | None:
    static_prefix_parts: list[str] = []
    matched: MatchedEmbeddedCommand | None = None
    for index, word in enumerate(command.words):
        static_text = word_static_text(word)
        if static_text is None:
            break
        if index == 0:
            static_text = normalize_command_name(static_text)
        static_prefix_parts.append(static_text)
        candidates = commands_by_name.get(' '.join(static_prefix_parts))
        if candidates is None:
            continue
        metadata_command = _matching_metadata_command(
            candidates,
            command.words[index + 1 :],
        )
        if metadata_command is None:
            continue
        matched = MatchedEmbeddedCommand(
            metadata_command=metadata_command, prefix_word_count=index + 1
        )
    return matched


def embedded_language_entry_for_annotation(
    command: Command,
    *,
    metadata_command: MetadataCommand,
    annotation: MetadataContext,
    prefix_word_count: int,
    current_namespace: str,
) -> EmbeddedLanguageEntry | None:
    argument_words = command.words[prefix_word_count:]
    argument_texts = tuple(word_static_text(word) for word in argument_words)
    argument_expanded = tuple(word.expanded for word in argument_words)

    owner_name: str | None = None
    owner_namespace = current_namespace
    if annotation.owner_selector is not None:
        owner_indices = select_argument_indices(
            annotation.owner_selector,
            argument_texts,
            metadata_command.options,
            argument_expanded,
        )
        if owner_indices is None or len(owner_indices) != 1:
            return None
        owner_index = owner_indices[0]
        if owner_index >= len(argument_words):
            return None

        owner_name = _static_owner_name(
            argument_words[owner_index],
            current_namespace=current_namespace,
        )
        if owner_name is None:
            return None
        owner_namespace = namespace_for_name(owner_name)

    body_indices = select_argument_indices(
        annotation.body_selector,
        argument_texts,
        metadata_command.options,
        argument_expanded,
    )
    if body_indices is None or not body_indices:
        return None
    if body_indices != tuple(range(body_indices[0], body_indices[-1] + 1)):
        return None

    if len(body_indices) == 1:
        return EmbeddedLanguageEntry(
            language=annotation.context_name,
            owner_name=owner_name,
            namespace=owner_namespace,
            script_word_index=prefix_word_count + body_indices[0],
            inline_command_start_index=None,
            inline_command_end_index=None,
        )

    return EmbeddedLanguageEntry(
        language=annotation.context_name,
        owner_name=owner_name,
        namespace=owner_namespace,
        script_word_index=None,
        inline_command_start_index=prefix_word_count + body_indices[0],
        inline_command_end_index=prefix_word_count + body_indices[-1],
    )


def _entry_start_index(entry: EmbeddedLanguageEntry) -> int:
    if entry.script_word_index is not None:
        return entry.script_word_index
    assert entry.inline_command_start_index is not None
    return entry.inline_command_start_index


def _entry_end_index(entry: EmbeddedLanguageEntry) -> int:
    if entry.script_word_index is not None:
        return entry.script_word_index
    assert entry.inline_command_end_index is not None
    return entry.inline_command_end_index


def _entries_overlap(left: EmbeddedLanguageEntry, right: EmbeddedLanguageEntry) -> bool:
    return _entry_start_index(left) <= _entry_end_index(right) and _entry_start_index(
        right
    ) <= _entry_end_index(left)


def _matching_metadata_command(
    candidates: tuple[MetadataCommand, ...],
    argument_words: tuple[Word, ...],
) -> MetadataCommand | None:
    argument_texts = tuple(word_static_text(word) for word in argument_words)
    argument_expanded = tuple(word.expanded for word in argument_words)
    argument_grouped = tuple(not isinstance(word, BareWord) for word in argument_words)
    exact_matches: list[MetadataCommand] = []
    fallback_matches: list[MetadataCommand] = []

    for candidate in candidates:
        match_state = _metadata_command_match_state(
            candidate,
            argument_texts,
            argument_expanded,
            argument_grouped,
        )
        if match_state == 'reject':
            continue
        if match_state == 'exact':
            exact_matches.append(candidate)
            continue
        fallback_matches.append(candidate)

    matched = tuple(exact_matches or fallback_matches)
    if not matched:
        return None

    unique_by_behavior: dict[
        tuple[tuple[object, ...], tuple[str, ...], tuple[object, ...]],
        MetadataCommand,
    ] = {}
    for candidate in matched:
        unique_by_behavior.setdefault(
            (
                tuple(candidate.options),
                candidate.subcommands,
                tuple(candidate.annotations),
            ),
            candidate,
        )

    if len(unique_by_behavior) != 1:
        return None
    return next(iter(unique_by_behavior.values()))


def _metadata_command_match_state(
    candidate: MetadataCommand,
    argument_texts: tuple[str | None, ...],
    argument_expanded: tuple[bool, ...],
    argument_grouped: tuple[bool, ...],
) -> str:
    exact = True
    if any(argument_expanded):
        exact = False

    structured_state = metadata_signature_match_state(
        candidate.signature,
        arg_texts=argument_texts,
        arg_expanded=argument_expanded,
        arg_grouped=argument_grouped,
    )
    if structured_state == 'reject':
        return 'reject'
    if structured_state == 'dynamic':
        exact = False

    arity = metadata_signature_arity(candidate.signature)
    if arity is not None and not any(argument_expanded) and not arity.accepts(len(argument_texts)):
        return 'reject'

    option_scan = scan_command_options(argument_texts, candidate.options, argument_expanded)
    if option_scan.state in {'unknown-option', 'missing-option-value'}:
        return 'reject'
    if option_scan.state in {'dynamic', 'unstable'}:
        exact = False

    return 'exact' if exact else 'fallback'


def _root_command_name(command_name: str) -> str:
    return normalize_command_name(command_name.split(' ', maxsplit=1)[0])


def _static_owner_name(
    word: Word,
    *,
    current_namespace: str,
) -> str | None:
    owner_text = word_static_text(word)
    if owner_text is None:
        return None
    return qualify_name(owner_text, current_namespace)
