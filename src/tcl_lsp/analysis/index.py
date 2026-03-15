from __future__ import annotations

from collections import defaultdict

from tcl_lsp.analysis.model import DocumentFacts, PackageIndexEntry, PackageProvide, ProcDecl


class WorkspaceIndex:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentFacts] = {}
        self._package_indexes_by_uri: dict[str, tuple[PackageIndexEntry, ...]] = {}
        self._procedures_by_qualified_name: dict[str, list[ProcDecl]] = defaultdict(list)
        self._provided_packages_by_name: dict[str, list[PackageProvide]] = defaultdict(list)
        self._package_index_entries_by_name: dict[str, list[PackageIndexEntry]] = defaultdict(list)

    def update(self, uri: str, facts: DocumentFacts) -> None:
        self.remove(uri)
        self._documents[uri] = facts
        for proc in facts.procedures:
            self._procedures_by_qualified_name.setdefault(proc.qualified_name, []).append(proc)
        for package in facts.package_provides:
            self._provided_packages_by_name.setdefault(package.name, []).append(package)

    def update_package_index(self, uri: str, entries: tuple[PackageIndexEntry, ...]) -> None:
        self.remove_package_index(uri)
        self._package_indexes_by_uri[uri] = entries
        for entry in entries:
            self._package_index_entries_by_name.setdefault(entry.name, []).append(entry)

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

        for package in existing.package_provides:
            current = self._provided_packages_by_name.get(package.name)
            if current is None:
                continue
            self._provided_packages_by_name[package.name] = [
                candidate
                for candidate in current
                if candidate.uri != package.uri or candidate.span != package.span
            ]
            if not self._provided_packages_by_name[package.name]:
                del self._provided_packages_by_name[package.name]

    def remove_package_index(self, uri: str) -> None:
        existing = self._package_indexes_by_uri.pop(uri, None)
        if existing is None:
            return

        for entry in existing:
            current = self._package_index_entries_by_name.get(entry.name)
            if current is None:
                continue
            self._package_index_entries_by_name[entry.name] = [
                candidate
                for candidate in current
                if candidate.uri != entry.uri or candidate.span != entry.span
            ]
            if not self._package_index_entries_by_name[entry.name]:
                del self._package_index_entries_by_name[entry.name]

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

    def provided_packages_for_name(self, package_name: str) -> tuple[PackageProvide, ...]:
        return tuple(self._provided_packages_by_name.get(package_name, ()))

    def package_index_entries_for_name(self, package_name: str) -> tuple[PackageIndexEntry, ...]:
        return tuple(self._package_index_entries_by_name.get(package_name, ()))

    def package_source_uris(self, package_name: str) -> tuple[str, ...]:
        source_uris: dict[str, None] = {}
        for entry in self.package_index_entries_for_name(package_name):
            if entry.source_uri is None:
                continue
            source_uris.setdefault(entry.source_uri, None)
        return tuple(source_uris)

    def has_package(self, package_name: str) -> bool:
        return bool(
            self._provided_packages_by_name.get(package_name)
            or self._package_index_entries_by_name.get(package_name)
        )

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
