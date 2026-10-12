from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from tcl_lsp.analysis.builtins import is_builtin_package, registry_for_packages
from tcl_lsp.analysis.facts.utils import extract_ifneeded_source_uri
from tcl_lsp.analysis.index import WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import (
    dependency_required_packages,
    metadata_dependency_overlay,
)
from tcl_lsp.analysis.model import DocumentFacts, PackageIndexEntry
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY, MetadataRegistry
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.project.paths import candidate_package_roots, read_source_file, source_id_to_path

type PackageIndexCatalog = tuple[tuple[str, tuple[PackageIndexEntry, ...]], ...]
type DocumentDescription = tuple[str, Path | None, DocumentFacts]
type LazyPackageIndex = tuple[Path, tuple[str, ...]]

_PACKAGE_IFNEEDED_NAME_RE = re.compile(
    r'(?m)(?:^|;)\s*package\s+ifneeded\s+(\{[^}\n]*\}|"[^"\n]*"|[^\s{}"\[\];]+)'
)


def build_package_index_catalog(
    target: Path,
    *,
    parser: Parser,
    library_paths: Sequence[Path] = (),
) -> PackageIndexCatalog:
    seen_paths: set[Path] = set()
    catalog_entries: list[tuple[str, tuple[PackageIndexEntry, ...]]] = []
    for root in _package_index_scan_roots(target, library_paths=library_paths):
        for pkg_index_path in discover_package_index_paths(root):
            if pkg_index_path in seen_paths:
                continue
            seen_paths.add(pkg_index_path)
            indexed_entry = load_package_index(
                pkg_index_path,
                parser=parser,
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


def discover_package_index_paths(
    package_root: Path,
) -> tuple[Path, ...]:
    return tuple(sorted(path.resolve(strict=False) for path in package_root.rglob('pkgIndex.tcl')))


def discover_lazy_package_indexes(
    package_root: Path,
) -> tuple[LazyPackageIndex, ...]:
    package_indexes: list[LazyPackageIndex] = []
    for pkg_index_path in discover_package_index_paths(package_root):
        try:
            text = read_source_file(pkg_index_path)
        except OSError:
            continue
        package_indexes.append((pkg_index_path, _package_index_names(text)))
    return tuple(package_indexes)


def load_package_index(
    path: Path,
    *,
    parser: Parser | None = None,
) -> tuple[str, tuple[PackageIndexEntry, ...]] | None:
    try:
        text = read_source_file(path)
    except OSError:
        return None

    pkg_index_uri = path.as_uri()
    local_parser = Parser() if parser is None else parser
    parse_result = local_parser.parse_document(path=pkg_index_uri, text=text)
    entries: list[PackageIndexEntry] = []
    for command in parse_result.script.commands:
        if len(command.words) < 4:
            continue
        if word_static_text(command.words[0]) != 'package':
            continue
        if word_static_text(command.words[1]) != 'ifneeded':
            continue

        package_name = word_static_text(command.words[2])
        version = word_static_text(command.words[3])
        if package_name is None or version is None:
            continue

        entries.append(
            PackageIndexEntry(
                uri=pkg_index_uri,
                name=package_name,
                version=version,
                source_uri=(
                    extract_ifneeded_source_uri(command.words[4], pkg_index_uri)
                    if len(command.words) >= 5
                    else None
                ),
                span=command.words[2].span,
            )
        )
    return (pkg_index_uri, tuple(entries))


def dependency_source_uris_for_facts(
    source_path: Path | None,
    facts: DocumentFacts,
    workspace_index: WorkspaceIndex,
    *,
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
) -> tuple[str, ...]:
    uris: dict[str, None] = {}
    if source_path is None:
        required_packages = {package_require.name for package_require in facts.package_requires}
        for directive in facts.source_directives:
            uris.setdefault(directive.target_uri, None)
    else:
        overlay = metadata_dependency_overlay(
            source_path,
            facts,
            workspace_index,
            metadata_registry=metadata_registry,
        )
        required_packages = {
            package_require.name for package_require in facts.package_requires
        } | set(overlay.required_packages)
        for source_uri in overlay.source_uris:
            uris.setdefault(source_uri, None)

    for package_name in required_packages:
        if is_builtin_package(package_name, metadata_registry=metadata_registry):
            continue
        for source_uri in workspace_index.package_source_uris(package_name):
            uris.setdefault(source_uri, None)
    return tuple(uris)


def prepare_dependencies(
    facts_by_uri: dict[str, DocumentFacts],
    *,
    workspace_index: WorkspaceIndex,
    load_facts: Callable[[str], DocumentFacts | None],
    extract_facts: Callable[[DocumentFacts, frozenset[str]], DocumentFacts],
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
    check_cancelled: Callable[[], None] | None = None,
) -> None:
    """Expand file-local facts with dependencies and their metadata.

    Inputs must exclude external package activation from earlier builds. This
    prevents removed requirements from surviving through a dependency cycle.
    Output facts carry the complete package set used by subsequent analysis.
    """
    failed_uris: set[str] = set()
    for uri, facts in facts_by_uri.items():
        workspace_index.update(uri, facts)

    while True:
        changed = False
        for facts in tuple(facts_by_uri.values()):
            if check_cancelled is not None:
                check_cancelled()
            for source_uri in dependency_source_uris_for_facts(
                source_id_to_path(facts.uri),
                facts,
                workspace_index,
                metadata_registry=metadata_registry,
            ):
                if source_uri in facts_by_uri or source_uri in failed_uris:
                    continue
                dependency_facts = load_facts(source_uri)
                if dependency_facts is None:
                    failed_uris.add(source_uri)
                    continue
                if dependency_facts.uri in facts_by_uri:
                    continue
                facts_by_uri[dependency_facts.uri] = dependency_facts
                workspace_index.update(dependency_facts.uri, dependency_facts)
                changed = True
        if changed:
            continue

        updated_facts: dict[str, DocumentFacts] = {}
        for uri, facts in facts_by_uri.items():
            if check_cancelled is not None:
                check_cancelled()
            source_path = source_id_to_path(uri)
            required_packages = facts.required_packages
            if source_path is not None:
                required_packages |= dependency_required_packages(
                    source_path, facts, workspace_index, metadata_registry=metadata_registry
                )
            if required_packages == facts.required_packages:
                continue
            if registry_for_packages(metadata_registry, required_packages) == registry_for_packages(
                metadata_registry, facts.required_packages
            ):
                facts = replace(facts, required_packages=required_packages)
            else:
                facts = extract_facts(facts, required_packages)
            updated_facts[uri] = facts
        if not updated_facts:
            return
        facts_by_uri.update(updated_facts)
        for uri, facts in updated_facts.items():
            workspace_index.update(uri, facts)


def reachable_document_uris[DocumentT](
    root_uri: str,
    *,
    documents_by_uri: dict[str, DocumentT],
    workspace_index: WorkspaceIndex,
    describe_document: Callable[[DocumentT], DocumentDescription],
    metadata_registry: MetadataRegistry = DEFAULT_METADATA_REGISTRY,
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
            metadata_registry=metadata_registry,
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


def _package_index_names(text: str) -> tuple[str, ...]:
    package_names: dict[str, None] = {}
    for match in _PACKAGE_IFNEEDED_NAME_RE.finditer(text):
        package_name = match.group(1).strip()
        if (
            len(package_name) >= 2
            and package_name[0] == package_name[-1]
            and package_name[0] in {'"', '{'}
        ):
            package_name = package_name[1:-1]
        if package_name:
            package_names.setdefault(package_name, None)
    return tuple(package_names)


__all__ = [
    'PackageIndexCatalog',
    'apply_package_index_catalog',
    'build_package_index_catalog',
    'dependency_source_uris_for_facts',
    'discover_lazy_package_indexes',
    'discover_package_index_paths',
    'load_package_index',
    'prepare_dependencies',
    'reachable_document_uris',
]
