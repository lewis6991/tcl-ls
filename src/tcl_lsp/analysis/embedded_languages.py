from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.arity import metadata_signature_arity
from tcl_lsp.analysis.facts.utils import namespace_for_name, normalize_command_name, qualify_name
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataCommand,
    MetadataContext,
    MetadataProcedure,
    all_metadata_commands,
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
    fallback_to_tcl: bool


@metadata_lru_cache(maxsize=1)
def _embedded_languages(
    metadata_registry: MetadataRegistry,
) -> dict[EmbeddedLanguageName, _EmbeddedLanguage]:
    commands_by_language: dict[str, dict[str, list[MetadataCommand]]] = {}
    root_commands_by_language: dict[str, set[str]] = {}
    procedure_roots_by_language: dict[str, set[str]] = {}
    binding_roots_by_language: dict[str, set[str]] = {}
    fallback_to_tcl_by_language: dict[str, bool] = {}

    for metadata_command in all_metadata_commands(metadata_registry=metadata_registry):
        if metadata_command.context_name is None:
            continue

        language_name = metadata_command.context_name
        commands_for_language = commands_by_language.setdefault(language_name, {})
        commands_for_language.setdefault(metadata_command.name, []).append(metadata_command)
        if metadata_command.context_fallback == 'tcl':
            fallback_to_tcl_by_language[language_name] = True

        root_name = _root_command_name(metadata_command.name)
        root_commands_by_language.setdefault(language_name, set()).add(root_name)
        if any(
            isinstance(annotation, MetadataProcedure) for annotation in metadata_command.annotations
        ):
            procedure_roots_by_language.setdefault(language_name, set()).add(root_name)
        if any(isinstance(annotation, MetadataBind) for annotation in metadata_command.annotations):
            binding_roots_by_language.setdefault(language_name, set()).add(root_name)

    return {
        language_name: _EmbeddedLanguage(
            name=language_name,
            commands_by_name={
                command_name: tuple(commands)
                for command_name, commands in commands_for_language.items()
            },
            root_commands=frozenset(root_commands_by_language.get(language_name, ())),
            procedure_roots=frozenset(procedure_roots_by_language.get(language_name, ())),
            binding_roots=frozenset(binding_roots_by_language.get(language_name, ())),
            fallback_to_tcl=fallback_to_tcl_by_language.get(language_name, False),
        )
        for language_name, commands_for_language in commands_by_language.items()
    }


@metadata_lru_cache(maxsize=1)
def _context_entry_commands(metadata_registry: MetadataRegistry) -> tuple[MetadataCommand, ...]:
    return tuple(
        metadata_command
        for metadata_command in all_metadata_commands(metadata_registry=metadata_registry)
        if metadata_command.context_name is None
        and any(
            isinstance(annotation, MetadataContext) for annotation in metadata_command.annotations
        )
    )


@metadata_lru_cache(maxsize=1)
def _context_entry_command_index(
    metadata_registry: MetadataRegistry,
) -> dict[str, tuple[MetadataCommand, ...]]:
    return _command_index(_context_entry_commands(metadata_registry))


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
    language = _embedded_languages(metadata_registry).get(language_name or '')
    if language is None:
        return True
    return language.fallback_to_tcl


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


def match_embedded_language_entry(
    command: Command,
    *,
    current_namespace: str,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> EmbeddedLanguageEntry | None:
    matched = _match_metadata_command(
        command,
        _context_entry_command_index(metadata_registry),
    )
    if matched is None:
        return None

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

    if len(entries) != 1:
        return None
    return next(iter(entries))


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


def _command_index(
    metadata_commands: tuple[MetadataCommand, ...],
) -> dict[str, tuple[MetadataCommand, ...]]:
    commands_by_name: dict[str, list[MetadataCommand]] = {}
    for metadata_command in metadata_commands:
        commands_by_name.setdefault(metadata_command.name, []).append(metadata_command)
    return {command_name: tuple(commands) for command_name, commands in commands_by_name.items()}


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
        )

    return EmbeddedLanguageEntry(
        language=annotation.context_name,
        owner_name=owner_name,
        namespace=owner_namespace,
        script_word_index=None,
        inline_command_start_index=prefix_word_count + body_indices[0],
    )


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
