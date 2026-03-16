from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from tcl_lsp.analysis.facts.utils import namespace_for_name, normalize_command_name, qualify_name
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataCommand,
    MetadataContext,
    MetadataProcedure,
    all_metadata_commands,
    select_argument_indices,
)
from tcl_lsp.parser import word_static_text
from tcl_lsp.parser.model import Command

type EmbeddedLanguageName = str


@dataclass(frozen=True, slots=True)
class EmbeddedLanguageEntry:
    language: EmbeddedLanguageName
    owner_name: str
    namespace: str
    script_word_index: int | None
    inline_command_start_index: int | None


@dataclass(frozen=True, slots=True)
class MatchedEmbeddedCommand:
    metadata_command: MetadataCommand
    prefix_word_count: int


@dataclass(frozen=True, slots=True)
class _EmbeddedLanguage:
    name: EmbeddedLanguageName
    commands_by_name: dict[str, tuple[MetadataCommand, ...]]
    root_commands: frozenset[str]
    procedure_roots: frozenset[str]
    binding_roots: frozenset[str]


@lru_cache(maxsize=1)
def _embedded_languages() -> dict[EmbeddedLanguageName, _EmbeddedLanguage]:
    commands_by_language: dict[str, dict[str, list[MetadataCommand]]] = {}
    root_commands_by_language: dict[str, set[str]] = {}
    procedure_roots_by_language: dict[str, set[str]] = {}
    binding_roots_by_language: dict[str, set[str]] = {}

    for metadata_command in all_metadata_commands():
        if metadata_command.context_name is None:
            continue

        language_name = metadata_command.context_name
        commands_for_language = commands_by_language.setdefault(language_name, {})
        commands_for_language.setdefault(metadata_command.name, []).append(metadata_command)

        root_name = _root_command_name(metadata_command.name)
        root_commands_by_language.setdefault(language_name, set()).add(root_name)
        if any(isinstance(annotation, MetadataProcedure) for annotation in metadata_command.annotations):
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
        )
        for language_name, commands_for_language in commands_by_language.items()
    }


@lru_cache(maxsize=1)
def _context_entry_commands() -> tuple[MetadataCommand, ...]:
    return tuple(
        metadata_command
        for metadata_command in all_metadata_commands()
        if metadata_command.context_name is None
        and any(isinstance(annotation, MetadataContext) for annotation in metadata_command.annotations)
    )


@lru_cache(maxsize=1)
def _context_entry_command_index() -> dict[str, tuple[MetadataCommand, ...]]:
    return _command_index(_context_entry_commands())


def match_embedded_language_command(
    command: Command,
    language_name: EmbeddedLanguageName | None,
) -> MatchedEmbeddedCommand | None:
    language = _embedded_languages().get(language_name or '')
    if language is None:
        return None
    return _match_metadata_command(command, language.commands_by_name)


def resolves_contextual_command(
    language_name: EmbeddedLanguageName | None,
    command_name: str,
) -> bool:
    language = _embedded_languages().get(language_name or '')
    if language is None:
        return False
    return normalize_command_name(command_name) in language.root_commands


def match_embedded_language_entry(
    command: Command,
    *,
    current_namespace: str,
) -> EmbeddedLanguageEntry | None:
    matched = _match_metadata_command(command, _context_entry_command_index())
    if matched is None:
        return None

    metadata_command = matched.metadata_command
    argument_words = command.words[matched.prefix_word_count :]
    argument_texts = tuple(word_static_text(word) for word in argument_words)
    argument_expanded = tuple(word.expanded for word in argument_words)
    for annotation in metadata_command.annotations:
        if not isinstance(annotation, MetadataContext):
            continue

        owner_indices = select_argument_indices(
            annotation.owner_selector,
            argument_texts,
            metadata_command.options,
            argument_expanded,
        )
        if owner_indices is None or len(owner_indices) != 1:
            continue
        owner_index = owner_indices[0]
        if owner_index >= len(argument_words):
            continue

        owner_name = _static_owner_name(
            argument_words[owner_index],
            current_namespace=current_namespace,
        )
        if owner_name is None:
            continue

        body_indices = select_argument_indices(
            annotation.body_selector,
            argument_texts,
            metadata_command.options,
            argument_expanded,
        )
        if body_indices is None or not body_indices:
            continue
        if body_indices != tuple(range(body_indices[0], body_indices[-1] + 1)):
            continue

        if len(body_indices) == 1:
            return EmbeddedLanguageEntry(
                language=annotation.context_name,
                owner_name=owner_name,
                namespace=namespace_for_name(owner_name),
                script_word_index=matched.prefix_word_count + body_indices[0],
                inline_command_start_index=None,
            )

        return EmbeddedLanguageEntry(
            language=annotation.context_name,
            owner_name=owner_name,
            namespace=namespace_for_name(owner_name),
            script_word_index=None,
            inline_command_start_index=matched.prefix_word_count + body_indices[0],
        )

    return None


def contextual_resolution_reason(language_name: EmbeddedLanguageName | None, command_name: str) -> str:
    language = _embedded_languages().get(language_name or '')
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
    return {
        command_name: tuple(commands)
        for command_name, commands in commands_by_name.items()
    }


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
        matched = MatchedEmbeddedCommand(
            metadata_command=candidates[0],
            prefix_word_count=index + 1,
        )
    return matched


def _root_command_name(command_name: str) -> str:
    return normalize_command_name(command_name.split(' ', maxsplit=1)[0])


def _static_owner_name(
    word,
    *,
    current_namespace: str,
) -> str | None:
    owner_text = word_static_text(word)
    if owner_text is None:
        return None
    return qualify_name(owner_text, current_namespace)
