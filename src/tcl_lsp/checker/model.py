from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.common import Diagnostic


@dataclass(frozen=True, slots=True)
class ProjectDiagnostic:
    path: Path
    diagnostic: Diagnostic


@dataclass(frozen=True, slots=True)
class CheckReport:
    root: Path
    source_count: int
    background_source_count: int
    diagnostics: tuple[ProjectDiagnostic, ...]
    source_text_by_path: dict[Path, str]
    elapsed_seconds: float

    @property
    def files_with_diagnostics(self) -> int:
        return len({item.path for item in self.diagnostics})

    @property
    def diagnostic_counts(self) -> Counter[str]:
        return Counter(item.diagnostic.code for item in self.diagnostics)
