from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

from tcl_lsp.analysis.facts import FactExtractor
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import metadata_dependency_overlay
from tcl_lsp.analysis.model import DocumentFacts, PackageIndexEntry
from tcl_lsp.parser import Parser
from tcl_lsp.project.paths import candidate_package_roots, read_source_file

type PackageIndexCatalog = tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...]
type DocumentDescription = tuple[str, Path | None, DocumentFacts]

DocumentT = TypeVar('DocumentT')


def build_package_index_catalog(
    target: Path,
    *,
    parser: Parser,
    extractor: FactExtractor,
    library_paths: Sequence[Path] = (),
) -> PackageIndexCatalog:
    seen_paths: set[Path] = set()
    catalog_entries: list[tuple[str, tuple[PackageIndexEntry, ...]]] = []
    for root in _package_index_scan_roots(target, library_paths=library_paths):
        for pkg_index_path in sorted(root.rglob('pkgIndex.tcl')):
            resolved_path = pkg_index_path.resolve(strict=False)
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            indexed_entry = _index_package_index(
                resolved_path,
                parser=parser,
                extractor=extractor,
            )
            if indexed_entry is not None:
                catalog_entries.append(indexed_entry)
    return tuple(catalog_entries)


def apply_package_index_catalog(
    workspace_index: WorkspaceIndex,
    package_index_catalog: PackageIndexCatalog,
) -> None:
    for pkg_index_uri, package_index_entries in package_index_catalog:
        workspace_index.update_package_index(pkg_index_uri, package_index_entries)


def scan_package_root(
    package_root: Path,
    *,
    parser: Parser,
    extractor: FactExtractor,
    workspace_index: WorkspaceIndex,
) -> PackageIndexCatalog:
    indexed_entries: list[tuple[str, tuple[PackageIndexEntry, ...]]] = []
    for pkg_index_path in sorted(package_root.rglob('pkgIndex.tcl')):
        indexed_entry = _index_package_index(
            pkg_index_path.resolve(strict=False),
            parser=parser,
            extractor=extractor,
        )
        if indexed_entry is None:
            continue
        indexed_entries.append(indexed_entry)
        workspace_index.update_package_index(*indexed_entry)
    return tuple(indexed_entries)


def dependency_source_uris_for_facts(
    source_path: Path | None,
    facts: DocumentFacts,
    workspace_index: WorkspaceIndex,
) -> tuple[str, ...]:
    uris: dict[str, None] = {}
    if source_path is None:
        required_packages = {package_require.name for package_require in facts.package_requires}
        for directive in facts.source_directives:
            uris.setdefault(directive.target_uri, None)
    else:
        overlay = metadata_dependency_overlay(source_path, facts, workspace_index)
        required_packages = {
            package_require.name for package_require in facts.package_requires
        } | set(overlay.required_packages)
        for source_uri in overlay.source_uris:
            uris.setdefault(source_uri, None)

    for package_name in required_packages:
        for source_uri in workspace_index.package_source_uris(package_name):
            uris.setdefault(source_uri, None)
    return tuple(uris)


def load_dependency_documents(
    documents_by_uri: dict[str, DocumentT],
    *,
    workspace_index: WorkspaceIndex,
    describe_document: Callable[[DocumentT], DocumentDescription],
    load_document: Callable[[str], DocumentT | None],
    on_document_loaded: Callable[[DocumentT], None] | None = None,
) -> tuple[DocumentT, ...]:
    failed_uris: set[str] = set()
    loaded_documents: list[DocumentT] = []

    while True:
        loaded_document = False
        for document in tuple(documents_by_uri.values()):
            _, source_path, facts = describe_document(document)
            for source_uri in dependency_source_uris_for_facts(
                source_path,
                facts,
                workspace_index,
            ):
                if source_uri in documents_by_uri or source_uri in failed_uris:
                    continue

                dependency_document = load_document(source_uri)
                if dependency_document is None:
                    failed_uris.add(source_uri)
                    continue

                dependency_uri, _, dependency_facts = describe_document(dependency_document)
                if dependency_uri in documents_by_uri:
                    continue

                documents_by_uri[dependency_uri] = dependency_document
                workspace_index.update(dependency_uri, dependency_facts)
                if on_document_loaded is not None:
                    on_document_loaded(dependency_document)
                loaded_documents.append(dependency_document)
                loaded_document = True
                break
            if loaded_document:
                break
        if not loaded_document:
            return tuple(loaded_documents)


def reachable_document_uris(
    root_uri: str,
    *,
    documents_by_uri: dict[str, DocumentT],
    workspace_index: WorkspaceIndex,
    describe_document: Callable[[DocumentT], DocumentDescription],
) -> tuple[str, ...]:
    reachable_uris: dict[str, None] = {}
    pending_uris = [root_uri]

    while pending_uris:
        uri = pending_uris.pop()
        if uri in reachable_uris:
            continue
        reachable_uris[uri] = None

        document = documents_by_uri.get(uri)
        if document is None:
            continue

        _, source_path, facts = describe_document(document)
        for dependency_uri in dependency_source_uris_for_facts(
            source_path,
            facts,
            workspace_index,
        ):
            if dependency_uri in reachable_uris:
                continue
            pending_uris.append(dependency_uri)

    return tuple(reachable_uris)


def _package_index_scan_roots(
    target: Path,
    *,
    library_paths: Sequence[Path] = (),
) -> tuple[Path, ...]:
    roots: dict[Path, None] = {}
    candidate_roots = tuple(candidate_package_roots(target))
    if candidate_roots:
        for package_root in candidate_roots:
            roots.setdefault(package_root.resolve(strict=False), None)
    elif target.is_dir():
        roots.setdefault(target, None)

    for library_path in library_paths:
        roots.setdefault(library_path.resolve(strict=False), None)
    return tuple(roots)


def _index_package_index(
    path: Path,
    *,
    parser: Parser,
    extractor: FactExtractor,
) -> tuple[str, tuple[PackageIndexEntry, ...]] | None:
    try:
        text = read_source_file(path)
    except OSError:
        return None

    pkg_index_uri = path.as_uri()
    parse_result = parser.parse_document(path=pkg_index_uri, text=text)
    facts = extractor.extract(parse_result, include_parse_result=False)
    return (pkg_index_uri, facts.package_index_entries)


__all__ = [
    'PackageIndexCatalog',
    'apply_package_index_catalog',
    'build_package_index_catalog',
    'dependency_source_uris_for_facts',
    'load_dependency_documents',
    'reachable_document_uris',
    'scan_package_root',
]
