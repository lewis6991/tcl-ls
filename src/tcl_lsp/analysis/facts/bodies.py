from __future__ import annotations

from dataclasses import dataclass, field, replace

from tcl_lsp.analysis.annotations import CommentAnnotation, TypeAlias
from tcl_lsp.analysis.facts.locations import SourceRelocation
from tcl_lsp.analysis.facts.utils import (
    command_rename_symbol_id,
    proc_symbol_id,
    variable_symbol_id,
)
from tcl_lsp.analysis.model import (
    CommandCall,
    CommandImport,
    CommandImportKind,
    CommandRename,
    NamespaceScope,
    PackageIndexEntry,
    PackageProvide,
    PackageRequire,
    ProcDecl,
    SourceDirective,
    ValueCheck,
    VarBinding,
    VariableReference,
)
from tcl_lsp.analysis.modules import ModuleSelection
from tcl_lsp.analysis.types import AliasDefinitions, CallTypes, TypeInfo
from tcl_lsp.cache import VersionCache
from tcl_lsp.common import Diagnostic, Position, Span
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.project.config import ModuleRule
from tcl_lsp.project.diagnostics import DiagnosticRule


@dataclass(frozen=True, slots=True)
class BodyInputs:
    """Semantic inputs to an isolated body. Locations and scope IDs are outputs."""

    text: str
    uri: str
    namespace: str
    embedded_language: str | None
    embedded_owner_name: str | None
    command_renames_enabled: bool
    metadata_registry: MetadataRegistry
    explicit_modules: tuple[str, ...]
    selected_modules: tuple[str, ...]
    module_rules: tuple[ModuleRule, ...]
    required_packages: frozenset[str]
    include_lexical_spans: bool
    already_lowered: bool
    exact_values: tuple[tuple[str, tuple[str, ...]], ...]
    types: tuple[tuple[str, TypeInfo], ...]
    type_aliases: AliasDefinitions
    call_types: CallTypes
    flow_namespace: str
    flow_procedure: bool
    flow_links: tuple[tuple[str, str | None], ...]
    flow_unknown_links: bool
    flow_reachable: bool
    guarded_values: tuple[tuple[str, tuple[str, ...]], ...]
    imports: tuple[tuple[str, CommandImportKind, str | None, str], ...]


@dataclass(frozen=True, slots=True)
class BodyFacts:
    """An isolated procedure body's output, without its declaration or parameters."""

    command_calls: tuple[CommandCall, ...]
    command_imports: tuple[CommandImport, ...]
    command_renames: tuple[CommandRename, ...]
    comment_spans: tuple[Span, ...]
    diagnostic_directives: tuple[tuple[int, DiagnosticRule], ...]
    directive_comments: tuple[Span, ...]
    diagnostics: tuple[Diagnostic, ...]
    module_scopes: tuple[ModuleSelection, ...]
    namespaces: tuple[NamespaceScope, ...]
    operator_spans: tuple[Span, ...]
    package_index_entries: tuple[PackageIndexEntry, ...]
    package_provides: tuple[PackageProvide, ...]
    package_requires: tuple[PackageRequire, ...]
    procedures: tuple[ProcDecl, ...]
    source_directives: tuple[SourceDirective, ...]
    string_spans: tuple[Span, ...]
    variable_bindings: tuple[VarBinding, ...]
    variable_references: tuple[VariableReference, ...]
    type_aliases: tuple[TypeAlias, ...]
    comment_annotations: tuple[CommentAnnotation, ...]
    value_checks: tuple[ValueCheck, ...]


@dataclass(slots=True)
class FactBuffer:
    value_checks: list[ValueCheck] = field(default_factory=list)
    command_calls: list[CommandCall] = field(default_factory=list)
    command_imports: list[CommandImport] = field(default_factory=list)
    command_renames: list[CommandRename] = field(default_factory=list)
    comment_spans: list[Span] = field(default_factory=list)
    diagnostic_directives: list[tuple[int, DiagnosticRule]] = field(default_factory=list)
    directive_comments: list[Span] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    module_scopes: list[ModuleSelection] = field(default_factory=list)
    namespaces: list[NamespaceScope] = field(default_factory=list)
    operator_spans: list[Span] = field(default_factory=list)
    package_index_entries: list[PackageIndexEntry] = field(default_factory=list)
    package_provides: list[PackageProvide] = field(default_factory=list)
    package_requires: list[PackageRequire] = field(default_factory=list)
    procedures: list[ProcDecl] = field(default_factory=list)
    source_directives: list[SourceDirective] = field(default_factory=list)
    string_spans: list[Span] = field(default_factory=list)
    variable_bindings: list[VarBinding] = field(default_factory=list)
    variable_references: list[VariableReference] = field(default_factory=list)
    type_aliases: list[TypeAlias] = field(default_factory=list)
    comment_annotations: list[CommentAnnotation] = field(default_factory=list)

    def freeze(self) -> BodyFacts:
        return BodyFacts(
            value_checks=tuple(self.value_checks),
            command_calls=tuple(self.command_calls),
            command_imports=tuple(self.command_imports),
            command_renames=tuple(self.command_renames),
            comment_spans=tuple(self.comment_spans),
            diagnostic_directives=tuple(self.diagnostic_directives),
            directive_comments=tuple(self.directive_comments),
            diagnostics=tuple(self.diagnostics),
            module_scopes=tuple(self.module_scopes),
            namespaces=tuple(self.namespaces),
            operator_spans=tuple(self.operator_spans),
            package_index_entries=tuple(self.package_index_entries),
            package_provides=tuple(self.package_provides),
            package_requires=tuple(self.package_requires),
            procedures=tuple(self.procedures),
            source_directives=tuple(self.source_directives),
            string_spans=tuple(self.string_spans),
            variable_bindings=tuple(self.variable_bindings),
            variable_references=tuple(self.variable_references),
            type_aliases=tuple(self.type_aliases),
            comment_annotations=tuple(self.comment_annotations),
        )

    def extend(self, facts: BodyFacts) -> None:
        self.value_checks.extend(facts.value_checks)
        self.command_calls.extend(facts.command_calls)
        self.command_imports.extend(facts.command_imports)
        self.command_renames.extend(facts.command_renames)
        self.comment_spans.extend(facts.comment_spans)
        self.diagnostic_directives.extend(facts.diagnostic_directives)
        self.directive_comments.extend(facts.directive_comments)
        self.diagnostics.extend(facts.diagnostics)
        self.module_scopes.extend(facts.module_scopes)
        self.namespaces.extend(facts.namespaces)
        self.operator_spans.extend(facts.operator_spans)
        self.package_index_entries.extend(facts.package_index_entries)
        self.package_provides.extend(facts.package_provides)
        self.package_requires.extend(facts.package_requires)
        self.procedures.extend(facts.procedures)
        self.source_directives.extend(facts.source_directives)
        self.string_spans.extend(facts.string_spans)
        self.variable_bindings.extend(facts.variable_bindings)
        self.variable_references.extend(facts.variable_references)
        self.type_aliases.extend(facts.type_aliases)
        self.comment_annotations.extend(facts.comment_annotations)


@dataclass(frozen=True, slots=True)
class CachedBody:
    origin: Position
    procedure_id: str
    facts: BodyFacts

    def at(self, origin: Position, procedure_id: str) -> CachedBody:
        if origin == self.origin and procedure_id == self.procedure_id:
            return self
        facts = _Relocation(self.origin, origin, self.procedure_id, procedure_id).apply(self.facts)
        return CachedBody(origin, procedure_id, facts)


class BodyAnalysisCache(VersionCache[BodyInputs, CachedBody]):
    pass


class _Relocation(SourceRelocation):
    """Move facts with unchanged body text to a new source origin and scope."""

    def __init__(
        self, before: Position, after: Position, old_procedure: str, new_procedure: str
    ) -> None:
        super().__init__(before, after)
        self._scopes = {old_procedure: new_procedure}

    def scope(self, scope: str) -> str:
        return self._scopes.get(scope, scope)

    def procedure(self, procedure: str | None) -> str | None:
        return self.scope(procedure) if procedure is not None else None

    def binding(self, binding: VarBinding) -> VarBinding:
        symbol_id = binding.symbol_id
        if binding.procedure_symbol_id is not None:
            prefix = f'var::{binding.uri}::{binding.procedure_symbol_id}::'
            if symbol_id.startswith(prefix):
                symbol_id = variable_symbol_id(
                    binding.uri, self.scope(binding.procedure_symbol_id), symbol_id[len(prefix) :]
                )
        return replace(
            binding,
            symbol_id=symbol_id,
            span=self.span(binding.span),
            scope_id=self.scope(binding.scope_id),
            procedure_symbol_id=self.procedure(binding.procedure_symbol_id),
        )

    def apply(self, facts: BodyFacts) -> BodyFacts:
        for proc in facts.procedures:
            self._scopes[proc.symbol_id] = proc_symbol_id(
                proc.uri, proc.qualified_name, self.position(proc.name_span.start).offset
            )
        return BodyFacts(
            value_checks=tuple(
                replace(
                    check,
                    command_span=self.span(check.command_span),
                    diagnostic=replace(check.diagnostic, span=self.span(check.diagnostic.span)),
                )
                for check in facts.value_checks
            ),
            comment_annotations=tuple(
                replace(item, span=self.span(item.span)) for item in facts.comment_annotations
            ),
            type_aliases=tuple(
                replace(alias, span=self.span(alias.span)) for alias in facts.type_aliases
            ),
            command_calls=tuple(
                replace(
                    call,
                    span=self.span(call.span),
                    name_span=self.span(call.name_span),
                    arg_spans=tuple(self.span(span) for span in call.arg_spans),
                    scope_id=self.scope(call.scope_id),
                    procedure_symbol_id=self.procedure(call.procedure_symbol_id),
                )
                for call in facts.command_calls
            ),
            command_imports=tuple(
                replace(item, span=self.span(item.span)) for item in facts.command_imports
            ),
            command_renames=tuple(
                replace(
                    item,
                    symbol_id=(
                        command_rename_symbol_id(
                            item.uri,
                            item.new_qualified_name,
                            self.position(item.new_name_span.start).offset,
                        )
                        if item.new_qualified_name is not None
                        else None
                    ),
                    span=self.span(item.span),
                    old_name_span=self.span(item.old_name_span),
                    new_name_span=self.span(item.new_name_span),
                    scope_id=self.scope(item.scope_id),
                    procedure_symbol_id=self.procedure(item.procedure_symbol_id),
                )
                for item in facts.command_renames
            ),
            comment_spans=tuple(self.span(span) for span in facts.comment_spans),
            directive_comments=tuple(self.span(span) for span in facts.directive_comments),
            diagnostic_directives=tuple(
                (
                    offset + self._after.offset - self._before.offset,
                    replace(
                        rule,
                        command=None if rule.command is None else self.span(rule.command),
                        directive_span=(
                            None if rule.directive_span is None else self.span(rule.directive_span)
                        ),
                    ),
                )
                for offset, rule in facts.diagnostic_directives
            ),
            diagnostics=tuple(
                replace(item, span=self.span(item.span)) for item in facts.diagnostics
            ),
            module_scopes=tuple(
                replace(item, span=self.span(item.span)) for item in facts.module_scopes
            ),
            namespaces=tuple(
                replace(
                    item, span=self.span(item.span), selection_span=self.span(item.selection_span)
                )
                for item in facts.namespaces
            ),
            operator_spans=tuple(self.span(span) for span in facts.operator_spans),
            package_index_entries=tuple(
                replace(item, span=self.span(item.span)) for item in facts.package_index_entries
            ),
            package_provides=tuple(
                replace(item, span=self.span(item.span)) for item in facts.package_provides
            ),
            package_requires=tuple(
                replace(item, span=self.span(item.span)) for item in facts.package_requires
            ),
            procedures=tuple(
                replace(
                    proc,
                    symbol_id=self.scope(proc.symbol_id),
                    span=self.span(proc.span),
                    name_span=self.span(proc.name_span),
                    body_span=self.span(proc.body_span) if proc.body_span is not None else None,
                    parameters=tuple(
                        replace(
                            param,
                            symbol_id=variable_symbol_id(
                                proc.uri, self.scope(proc.symbol_id), param.name
                            ),
                            span=self.span(param.span),
                        )
                        for param in proc.parameters
                    ),
                )
                for proc in facts.procedures
            ),
            source_directives=tuple(
                replace(item, span=self.span(item.span)) for item in facts.source_directives
            ),
            string_spans=tuple(self.span(span) for span in facts.string_spans),
            variable_bindings=tuple(self.binding(item) for item in facts.variable_bindings),
            variable_references=tuple(
                replace(
                    item,
                    span=self.span(item.span),
                    scope_id=self.scope(item.scope_id),
                    procedure_symbol_id=self.procedure(item.procedure_symbol_id),
                )
                for item in facts.variable_references
            ),
        )
