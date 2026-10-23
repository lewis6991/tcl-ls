from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from tcl_lsp.common import Diagnostic

from .ambiguous_command import AmbiguousCommandChecker
from .ambiguous_variable import AmbiguousVariableChecker
from .base import (
    DiagnosticChecker,
    DiagnosticContext,
    ResolvedCommand,
    ResolvedCommandTarget,
    ResolvedVariable,
)
from .duplicate_proc import DuplicateProcChecker
from .incompatible_environment import IncompatibleEnvironmentChecker
from .invalid_arguments import InvalidArgumentsChecker
from .invalid_regex import InvalidRegexChecker
from .missing_option_value import MissingOptionValueChecker
from .unknown_option import UnknownOptionChecker
from .unknown_subcommand import UnknownSubcommandChecker
from .unreachable_code import UnreachableCodeChecker
from .unresolved_command import UnresolvedCommandChecker
from .unresolved_package import UnresolvedPackageChecker
from .unresolved_variable import UnresolvedVariableChecker
from .unused_proc import UnusedProcChecker
from .unused_variable import UnusedVariableChecker
from .value_constraints import ValueConstraintChecker
from .wrong_argument_count import WrongArgumentCountChecker

DIAGNOSTIC_CHECKERS: Final[tuple[DiagnosticChecker, ...]] = (
    DuplicateProcChecker(),
    UnresolvedPackageChecker(),
    UnresolvedCommandChecker(),
    AmbiguousCommandChecker(),
    WrongArgumentCountChecker(),
    InvalidArgumentsChecker(),
    UnknownSubcommandChecker(),
    UnknownOptionChecker(),
    MissingOptionValueChecker(),
    InvalidRegexChecker(),
    ValueConstraintChecker(),
    IncompatibleEnvironmentChecker(),
    UnreachableCodeChecker(),
    AmbiguousVariableChecker(),
    UnresolvedVariableChecker(),
    UnusedVariableChecker(),
    UnusedProcChecker(),
)


def collect_diagnostics(context: DiagnosticContext) -> Iterable[Diagnostic]:
    diagnostics = [
        diagnostic for checker in DIAGNOSTIC_CHECKERS for diagnostic in checker.check(context)
    ]
    unreachable_spans = [d.span for d in diagnostics if d.code == 'unreachable-code']
    for diagnostic in diagnostics:
        if diagnostic.code in {'unused-variable', 'unused-proc'} and any(
            span.start.offset <= diagnostic.span.start.offset < span.end.offset
            for span in unreachable_spans
        ):
            continue
        yield diagnostic


__all__ = [
    'DiagnosticContext',
    'ResolvedCommand',
    'ResolvedCommandTarget',
    'ResolvedVariable',
    'collect_diagnostics',
]
