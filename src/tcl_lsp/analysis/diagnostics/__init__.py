from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from tcl_lsp.common import Diagnostic

from .ambiguous_command import AmbiguousCommandChecker
from .base import (
    DiagnosticChecker,
    DiagnosticContext,
    ResolvedCommand,
    ResolvedCommandTarget,
    ResolvedVariable,
)
from .duplicate_proc import DuplicateProcChecker
from .missing_option_value import MissingOptionValueChecker
from .unknown_option import UnknownOptionChecker
from .unresolved_command import UnresolvedCommandChecker
from .unresolved_package import UnresolvedPackageChecker
from .unresolved_variable import UnresolvedVariableChecker
from .wrong_argument_count import WrongArgumentCountChecker

DIAGNOSTIC_CHECKERS: Final[tuple[DiagnosticChecker, ...]] = (
    DuplicateProcChecker(),
    UnresolvedPackageChecker(),
    UnresolvedCommandChecker(),
    AmbiguousCommandChecker(),
    WrongArgumentCountChecker(),
    UnknownOptionChecker(),
    MissingOptionValueChecker(),
    UnresolvedVariableChecker(),
)

def collect_diagnostics(context: DiagnosticContext) -> Iterable[Diagnostic]:
    for checker in DIAGNOSTIC_CHECKERS:
        yield from checker.check(context)


__all__ = [
    'DiagnosticContext',
    'ResolvedCommand',
    'ResolvedCommandTarget',
    'ResolvedVariable',
    'collect_diagnostics',
]
