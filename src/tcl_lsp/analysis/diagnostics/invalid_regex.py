from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable
from functools import lru_cache
from typing import ClassVar, override

from tcl_lsp.analysis.builtins import BuiltinCommand
from tcl_lsp.analysis.metadata_commands import MetadataOption, scan_command_options
from tcl_lsp.common import Diagnostic

from .base import AnalysisDiagnosticSeverity, DiagnosticChecker, DiagnosticContext
from .helpers import builtin_shared_option_specs, resolved_command_calls

_REGEX_COMMANDS = frozenset({'regexp', 'regsub'})
_REGEXP_VALIDATE_SCRIPT = """
set pattern $::env(TCL_LS_PATTERN)
set expanded $::env(TCL_LS_EXPANDED)
set command [list regexp --]
if {$expanded eq "1"} {
    set command [list regexp -expanded --]
}
if {[catch {{*}$command $pattern ""} message]} {
    puts $message
    exit 1
}
"""


class InvalidRegexChecker(DiagnosticChecker):
    CODE: ClassVar[str] = 'invalid-regex'
    SEVERITY: ClassVar[AnalysisDiagnosticSeverity] = 'error'

    @override
    def check(self, context: DiagnosticContext) -> Iterable[Diagnostic]:
        for command_call, command_target in resolved_command_calls(context):
            if not isinstance(command_target, BuiltinCommand):
                continue
            if command_target.name not in _REGEX_COMMANDS:
                continue

            options = builtin_shared_option_specs(command_target)
            if options is None:
                continue

            pattern_index = _pattern_argument_index(
                command_call.arg_texts,
                options,
                command_call.arg_expanded,
            )
            if pattern_index is None:
                continue

            if pattern_index >= len(command_call.arg_spans):
                continue

            pattern_text = command_call.arg_texts[pattern_index]
            if pattern_text is None:
                continue

            error_message = _regexp_compile_error(
                pattern_text,
                expanded=_uses_expanded_regexp_mode(command_call.arg_texts, options, pattern_index),
            )
            if error_message is None:
                continue

            yield self.emit(
                span=command_call.arg_spans[pattern_index],
                message=(
                    f'Invalid regular expression for command `{command_target.name}`; '
                    f'{error_message}.'
                ),
            )


def _pattern_argument_index(
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    arg_expanded: tuple[bool, ...],
) -> int | None:
    scan_result = scan_command_options(arg_texts, options, arg_expanded)
    if scan_result.state != 'ok' or not scan_result.positional_indices:
        return None
    return scan_result.positional_indices[0]


def _uses_expanded_regexp_mode(
    arg_texts: tuple[str | None, ...],
    options: tuple[MetadataOption, ...],
    pattern_index: int,
) -> bool:
    option_specs = {option.name: option for option in options}
    index = 0
    expanded = False

    while index < min(pattern_index, len(arg_texts)):
        arg_text = arg_texts[index]
        if arg_text is None:
            return False

        option = option_specs.get(arg_text)
        if option is None:
            return False
        if arg_text == '-expanded':
            expanded = True
        if option.kind == 'flag':
            index += 1
            continue
        if option.kind == 'value':
            index += 2
            continue
        return expanded

    return expanded


@lru_cache(maxsize=512)
def _regexp_compile_error(pattern: str, *, expanded: bool) -> str | None:
    tclsh_path = shutil.which('tclsh')
    if tclsh_path is None:
        return None

    try:
        completed = subprocess.run(
            [tclsh_path],
            input=_REGEXP_VALIDATE_SCRIPT,
            text=True,
            capture_output=True,
            timeout=2,
            env={
                **os.environ,
                'TCL_LS_PATTERN': pattern,
                'TCL_LS_EXPANDED': '1' if expanded else '0',
            },
            check=False,
        )
    except OSError, ValueError, subprocess.TimeoutExpired:
        return None

    if completed.returncode == 0:
        return None

    message = completed.stdout.strip() or completed.stderr.strip()
    if not message:
        return 'could not compile the regular expression pattern'
    if message.endswith('.'):
        return message[:-1]
    return message
