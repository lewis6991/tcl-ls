from __future__ import annotations

from lsprotocol import types

from tcl_lsp.analysis.control_flow import (
    CatchControlFlowCommand,
    ControlFlowScript,
    ForControlFlowCommand,
    IfControlFlowCommand,
    NamespaceEvalControlFlowCommand,
    ProcControlFlowCommand,
    SwitchControlFlowCommand,
    TryControlFlowCommand,
    WhileControlFlowCommand,
)
from tcl_lsp.common import Span
from tcl_lsp.lsp.state import ManagedDocument


def folding_ranges(document: ManagedDocument) -> tuple[types.FoldingRange, ...]:
    ranges: list[types.FoldingRange] = []
    seen: set[tuple[int, int, str | None]] = set()

    for namespace_span in _namespace_eval_spans(document.facts.control_flow):
        _add_folding_range(
            ranges,
            seen,
            namespace_span,
            kind=types.FoldingRangeKind.Region,
        )

    for procedure in sorted(document.facts.procedures, key=lambda item: item.span.start.offset):
        _add_folding_range(
            ranges,
            seen,
            procedure.body_span if procedure.body_span is not None else procedure.span,
            kind=types.FoldingRangeKind.Region,
        )

    return tuple(ranges)


def _add_folding_range(
    ranges: list[types.FoldingRange],
    seen: set[tuple[int, int, str | None]],
    span: Span | None,
    *,
    kind: types.FoldingRangeKind,
) -> None:
    if span is None or span.end.line <= span.start.line:
        return

    key = (span.start.line, span.end.line, str(kind))
    if key in seen:
        return
    seen.add(key)
    ranges.append(
        types.FoldingRange(
            start_line=span.start.line,
            end_line=span.end.line,
            kind=kind,
        )
    )


def _namespace_eval_spans(script: ControlFlowScript) -> tuple[Span, ...]:
    spans: list[Span] = []
    for command in script.commands:
        if isinstance(command, NamespaceEvalControlFlowCommand):
            spans.append(command.span)
        for nested_script in _nested_scripts(command):
            spans.extend(_namespace_eval_spans(nested_script))
    return tuple(spans)


def _nested_scripts(command: object) -> tuple[ControlFlowScript, ...]:
    scripts: list[ControlFlowScript] = []
    if isinstance(
        command,
        (
            ProcControlFlowCommand,
            NamespaceEvalControlFlowCommand,
            CatchControlFlowCommand,
            WhileControlFlowCommand,
        ),
    ):
        if command.body is not None:
            scripts.append(command.body)
    elif isinstance(command, ForControlFlowCommand):
        for script in (command.start_body, command.next_body, command.body):
            if script is not None:
                scripts.append(script)
    elif isinstance(command, IfControlFlowCommand):
        for clause in command.clauses:
            if clause.body is not None:
                scripts.append(clause.body)
        if command.else_body is not None:
            scripts.append(command.else_body)
    elif isinstance(command, TryControlFlowCommand):
        if command.body is not None:
            scripts.append(command.body)
        scripts.extend(handler for handler in command.handlers if handler is not None)
        if command.finally_body is not None:
            scripts.append(command.finally_body)
    elif isinstance(command, SwitchControlFlowCommand):
        scripts.extend(command.branch_bodies)
    return tuple(scripts)
