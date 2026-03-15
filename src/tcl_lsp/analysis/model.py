from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tcl_lsp.common import Diagnostic, DocumentSymbol, HoverInfo, Location, Span, SymbolKind
from tcl_lsp.parser.model import ParseResult

type BindingKind = Literal['parameter', 'set', 'foreach', 'catch']
type ReferenceKind = Literal['command', 'variable']
type ResolutionState = Literal['resolved', 'unresolved', 'ambiguous', 'dynamic']


@dataclass(frozen=True, slots=True)
class NamespaceScope:
    uri: str
    name: str
    qualified_name: str
    span: Span
    selection_span: Span


@dataclass(frozen=True, slots=True)
class ParameterDecl:
    symbol_id: str
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class ProcDecl:
    symbol_id: str
    uri: str
    name: str
    qualified_name: str
    namespace: str
    span: Span
    name_span: Span
    parameters: tuple[ParameterDecl, ...]
    documentation: str | None
    body_span: Span | None


@dataclass(frozen=True, slots=True)
class PackageRequire:
    uri: str
    name: str
    version_constraints: tuple[str, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class PackageProvide:
    uri: str
    name: str
    version: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class PackageIndexEntry:
    uri: str
    name: str
    version: str | None
    source_uri: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class VarBinding:
    symbol_id: str
    uri: str
    name: str
    scope_id: str
    namespace: str
    procedure_symbol_id: str | None
    kind: BindingKind
    span: Span


@dataclass(frozen=True, slots=True)
class CommandCall:
    uri: str
    name: str | None
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None
    span: Span
    name_span: Span
    dynamic: bool


@dataclass(frozen=True, slots=True)
class VariableReference:
    uri: str
    name: str
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None
    span: Span


@dataclass(frozen=True, slots=True)
class ReferenceSite:
    uri: str
    kind: ReferenceKind
    name: str | None
    namespace: str
    scope_id: str
    procedure_symbol_id: str | None
    span: Span
    dynamic: bool


@dataclass(frozen=True, slots=True)
class AnalysisUncertainty:
    state: ResolutionState
    reason: str


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    reference: ReferenceSite
    uncertainty: AnalysisUncertainty
    target_symbol_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DefinitionTarget:
    symbol_id: str
    name: str
    kind: SymbolKind
    location: Location
    detail: str


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    symbol_id: str
    reference: ReferenceSite


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    uri: str
    parse_result: ParseResult
    namespaces: tuple[NamespaceScope, ...]
    procedures: tuple[ProcDecl, ...]
    package_requires: tuple[PackageRequire, ...]
    package_provides: tuple[PackageProvide, ...]
    package_index_entries: tuple[PackageIndexEntry, ...]
    variable_bindings: tuple[VarBinding, ...]
    command_calls: tuple[CommandCall, ...]
    variable_references: tuple[VariableReference, ...]
    document_symbols: tuple[DocumentSymbol, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    uri: str
    diagnostics: tuple[Diagnostic, ...]
    definitions: tuple[DefinitionTarget, ...]
    resolutions: tuple[ResolutionResult, ...]
    resolved_references: tuple[ResolvedReference, ...]
    document_symbols: tuple[DocumentSymbol, ...]
    hovers: tuple[HoverInfo, ...]
