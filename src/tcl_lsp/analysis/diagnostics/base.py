from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, final

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.model import (
    CommandCall,
    DocumentFacts,
    ProcDecl,
    ResolutionResult,
    VariableReference,
)
from tcl_lsp.common import Diagnostic, DiagnosticTag, Span
from tcl_lsp.metadata_paths import MetadataRegistry

type CommandCallKey = tuple[str, int, int, int, int]
type ResolvedCommandTarget = BuiltinCommand | ProcDecl
type AnalysisDiagnosticSeverity = Literal['error', 'warning', 'hint']


@dataclass(frozen=True, slots=True)
class ResolvedCommand:
    command_call: CommandCall
    resolution: ResolutionResult


@dataclass(frozen=True, slots=True)
class ResolvedVariable:
    variable_reference: VariableReference
    resolution: ResolutionResult


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    facts: DocumentFacts
    workspace_index: WorkspaceIndex
    metadata_registry: MetadataRegistry
    required_packages: frozenset[str]
    command_targets: Mapping[CommandCallKey, ResolvedCommandTarget]
    command_resolutions: tuple[ResolvedCommand, ...]
    variable_resolutions: tuple[ResolvedVariable, ...]


class DiagnosticChecker(ABC):
    __slots__ = ()

    CODE: ClassVar[str]
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity]

    @abstractmethod
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        raise NotImplementedError

    @final
    def emit(
        self,
        *,
        span: Span,
        message: str,
        tags: tuple[DiagnosticTag, ...] = (),
    ) -> Diagnostic:
        return Diagnostic(
            span=span,
            severity=self.SEVERITY,
            message=message,
            source='analysis',
            code=self.CODE,
            tags=tags,
        )
