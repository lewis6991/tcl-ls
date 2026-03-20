from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.facts.lowering import (
    LoweredCatchCommand,
    LoweredCommand,
    LoweredForCommand,
    LoweredIfCommand,
    LoweredNamespaceEvalCommand,
    LoweredProcCommand,
    LoweredScript,
    LoweredScriptBody,
    LoweredSwitchCommand,
    LoweredTryCommand,
    LoweredWhileCommand,
)
from tcl_lsp.common import Span


@dataclass(frozen=True, slots=True)
class ControlFlowScript:
    commands: tuple[ControlFlowCommand, ...]


@dataclass(frozen=True, slots=True)
class IfControlFlowClause:
    condition_text: str | None
    body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class ControlFlowCommandBase:
    span: Span
    name_span: Span | None
    command_name: str | None


@dataclass(frozen=True, slots=True)
class GenericControlFlowCommand(ControlFlowCommandBase):
    pass


@dataclass(frozen=True, slots=True)
class ProcControlFlowCommand(ControlFlowCommandBase):
    body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class NamespaceEvalControlFlowCommand(ControlFlowCommandBase):
    body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class ForControlFlowCommand(ControlFlowCommandBase):
    start_body: ControlFlowScript | None
    condition_text: str | None
    next_body: ControlFlowScript | None
    body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class IfControlFlowCommand(ControlFlowCommandBase):
    clauses: tuple[IfControlFlowClause, ...]
    else_body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class CatchControlFlowCommand(ControlFlowCommandBase):
    body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class TryControlFlowCommand(ControlFlowCommandBase):
    body: ControlFlowScript | None
    handlers: tuple[ControlFlowScript | None, ...]
    finally_body: ControlFlowScript | None


@dataclass(frozen=True, slots=True)
class SwitchControlFlowCommand(ControlFlowCommandBase):
    has_default: bool
    branch_bodies: tuple[ControlFlowScript, ...]


@dataclass(frozen=True, slots=True)
class WhileControlFlowCommand(ControlFlowCommandBase):
    condition_text: str | None
    body: ControlFlowScript | None


type ControlFlowCommand = (
    GenericControlFlowCommand
    | ProcControlFlowCommand
    | NamespaceEvalControlFlowCommand
    | ForControlFlowCommand
    | IfControlFlowCommand
    | CatchControlFlowCommand
    | TryControlFlowCommand
    | SwitchControlFlowCommand
    | WhileControlFlowCommand
)


def build_control_flow_script(script: LoweredScript) -> ControlFlowScript:
    return ControlFlowScript(commands=tuple(_build_command(command) for command in script.commands))


def _build_command(command: LoweredCommand) -> ControlFlowCommand:
    base = _command_base(command)
    if isinstance(command, LoweredProcCommand):
        return ProcControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            body=_build_body(command.body),
        )
    if isinstance(command, LoweredNamespaceEvalCommand):
        return NamespaceEvalControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            body=_build_body(command.body),
        )
    if isinstance(command, LoweredForCommand):
        return ForControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            start_body=_build_body(command.start_body),
            condition_text=command.condition.text if command.condition is not None else None,
            next_body=_build_body(command.next_body),
            body=_build_body(command.body),
        )
    if isinstance(command, LoweredIfCommand):
        return IfControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            clauses=tuple(
                IfControlFlowClause(
                    condition_text=clause.condition.text if clause.condition is not None else None,
                    body=_build_body(clause.body),
                )
                for clause in command.clauses
            ),
            else_body=_build_body(command.else_body),
        )
    if isinstance(command, LoweredCatchCommand):
        return CatchControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            body=_build_body(command.body),
        )
    if isinstance(command, LoweredTryCommand):
        return TryControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            body=_build_body(command.body),
            handlers=tuple(_build_body(handler.body) for handler in command.handlers),
            finally_body=_build_body(command.finally_body),
        )
    if isinstance(command, LoweredSwitchCommand):
        return SwitchControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            has_default=any(
                pattern == 'default'
                for branch_patterns in command.branch_patterns
                for pattern in branch_patterns
            ),
            branch_bodies=tuple(
                build_control_flow_script(body.script) for body in command.branch_bodies
            ),
        )
    if isinstance(command, LoweredWhileCommand):
        return WhileControlFlowCommand(
            span=base.span,
            name_span=base.name_span,
            command_name=base.command_name,
            condition_text=command.condition.text if command.condition is not None else None,
            body=_build_body(command.body),
        )
    return GenericControlFlowCommand(
        span=base.span,
        name_span=base.name_span,
        command_name=base.command_name,
    )


def _build_body(body: LoweredScriptBody | None) -> ControlFlowScript | None:
    if body is None:
        return None
    return build_control_flow_script(body.script)


def _command_base(command: LoweredCommand) -> ControlFlowCommandBase:
    syntax_command = command.command
    name_span = syntax_command.words[0].span if syntax_command.words else None
    return ControlFlowCommandBase(
        span=syntax_command.span,
        name_span=name_span,
        command_name=command.command_name,
    )
