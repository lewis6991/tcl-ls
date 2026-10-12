from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis.flow import VariableFlowState
from tcl_lsp.analysis.flow.exprs import eval_expr_text
from tcl_lsp.common import Span
from tcl_lsp.metadata_paths import MetadataRegistry
from tcl_lsp.project.config import ModuleRule


@dataclass(frozen=True, slots=True)
class ModuleSelection:
    span: Span
    modules: tuple[str, ...]


def active_modules(
    explicit: tuple[str, ...],
    rules: tuple[ModuleRule, ...],
    state: VariableFlowState,
) -> tuple[str, ...]:
    modules = list(explicit)
    for rule in rules:
        # Static expression analysis only; never execute command substitutions.
        result = eval_expr_text(state, rule.condition, lambda _script, _state: ())
        if result.true_possible and not result.false_possible and rule.name not in modules:
            modules.append(rule.name)
    return tuple(modules)


def registry_at_offset(
    registry: MetadataRegistry, scopes: tuple[ModuleSelection, ...], offset: int
) -> MetadataRegistry:
    # A later directive or a nested Tcl body has the narrower containing span.
    scope = min(
        (scope for scope in scopes if scope.span.start.offset <= offset <= scope.span.end.offset),
        key=lambda scope: scope.span.end.offset - scope.span.start.offset,
        default=None,
    )
    return registry if scope is None else registry.with_modules(scope.modules)
