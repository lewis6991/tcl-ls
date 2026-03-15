from __future__ import annotations

from collections import defaultdict

from tcl_lsp.analysis.model import DocumentFacts, ProcDecl


class WorkspaceIndex:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentFacts] = {}
        self._procedures_by_qualified_name: dict[str, list[ProcDecl]] = defaultdict(list)

    def update(self, uri: str, facts: DocumentFacts) -> None:
        self.remove(uri)
        self._documents[uri] = facts
        for proc in facts.procedures:
            self._procedures_by_qualified_name.setdefault(proc.qualified_name, []).append(proc)

    def remove(self, uri: str) -> None:
        existing = self._documents.pop(uri, None)
        if existing is None:
            return

        for proc in existing.procedures:
            current = self._procedures_by_qualified_name.get(proc.qualified_name)
            if current is None:
                continue
            self._procedures_by_qualified_name[proc.qualified_name] = [
                candidate for candidate in current if candidate.symbol_id != proc.symbol_id
            ]
            if not self._procedures_by_qualified_name[proc.qualified_name]:
                del self._procedures_by_qualified_name[proc.qualified_name]

    def resolve_procedure(self, raw_name: str, namespace: str) -> tuple[ProcDecl, ...]:
        matches: list[ProcDecl] = []
        seen: set[str] = set()
        for candidate_name in _procedure_candidates(raw_name, namespace):
            for proc in self._procedures_by_qualified_name.get(candidate_name, []):
                if proc.symbol_id in seen:
                    continue
                seen.add(proc.symbol_id)
                matches.append(proc)
        return tuple(matches)

    def procedures_for_name(self, qualified_name: str) -> tuple[ProcDecl, ...]:
        return tuple(self._procedures_by_qualified_name.get(qualified_name, []))

    def documents(self) -> tuple[DocumentFacts, ...]:
        return tuple(self._documents.values())


def _procedure_candidates(raw_name: str, namespace: str) -> list[str]:
    if raw_name.startswith('::'):
        return [_normalize_qualified_name(raw_name)]

    namespace_segments = [segment for segment in namespace.split('::') if segment]
    candidates: list[str] = []
    while namespace_segments:
        candidates.append('::' + '::'.join((*namespace_segments, raw_name)))
        namespace_segments = namespace_segments[:-1]
    candidates.append(f'::{raw_name}')
    return candidates


def _normalize_qualified_name(name: str) -> str:
    segments = [segment for segment in name.split('::') if segment]
    if not segments:
        return '::'
    return '::' + '::'.join(segments)
