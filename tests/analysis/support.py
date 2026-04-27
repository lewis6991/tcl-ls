from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tcl_lsp.analysis import (
    AnalysisResult,
    DocumentFacts,
    FactExtractor,
    Resolver,
    WorkspaceIndex,
)
from tcl_lsp.parser import Parser


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    facts: DocumentFacts
    analysis: AnalysisResult


def analyze_document(parser: Parser, uri: str, text: str) -> AnalysisSnapshot:
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(uri, text)
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)
    return AnalysisSnapshot(facts=facts, analysis=analysis)


def analyze_path(
    parser: Parser,
    source_path: Path,
    *,
    metadata_paths: tuple[Path, ...] = (),
) -> tuple[DocumentFacts, AnalysisResult]:
    from tcl_lsp.metadata_paths import create_metadata_registry

    metadata_registry = create_metadata_registry(metadata_paths)
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    resolver = Resolver(metadata_registry=metadata_registry)
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        source_path.as_uri(),
        source_path.read_text(encoding='utf-8'),
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)
    return facts, analysis


def analyze_workspace(
    parser: Parser,
    documents: Iterable[tuple[str, str]],
    target_uri: str,
) -> AnalysisSnapshot:
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()
    facts_by_uri: dict[str, DocumentFacts] = {}

    for uri, text in documents:
        parse_result = parser.parse_document(uri, text)
        facts = extractor.extract(parse_result)
        workspace.update(facts.uri, facts)
        facts_by_uri[uri] = facts

    target_facts = facts_by_uri[target_uri]
    analysis = resolver.analyze(target_uri, target_facts, workspace)
    return AnalysisSnapshot(facts=target_facts, analysis=analysis)
