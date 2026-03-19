from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, override

from tcl_lsp.analysis.builtins import is_builtin_package
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext


class UnresolvedPackageChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'unresolved-package'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'warning'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for package_require in context.facts.package_requires:
            if is_builtin_package(
                package_require.name,
                metadata_registry=context.metadata_registry,
            ) or context.workspace_index.has_package(package_require.name):
                continue
            yield self.emit(
                span=package_require.span,
                message=f'Unresolved package `{package_require.name}`.',
            )
