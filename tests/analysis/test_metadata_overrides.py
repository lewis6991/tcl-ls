from __future__ import annotations

from pathlib import Path

from tcl_lsp.analysis import FactExtractor, WorkspaceIndex
from tcl_lsp.analysis.metadata_effects import dependency_required_packages
from tcl_lsp.metadata_paths import create_metadata_registry
from tcl_lsp.parser import Parser

from .support import analyze_document as _analyze
from .support import analyze_path as _analyze_path


def test_analysis_prefers_workspace_procedures_over_builtin_metadata(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///shadow_builtin.tcl',
        'namespace eval n {\n'
        '    proc set {value} {\n'
        '        return $value\n'
        '    }\n'
        '    proc run {} {\n'
        '        set local\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    local_set = next(proc for proc in facts.procedures if proc.qualified_name == '::n::set')
    set_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'set'
    )

    assert set_resolution.uncertainty.state == 'resolved'
    assert set_resolution.target_symbol_ids == (local_set.symbol_id,)


def test_analysis_prefers_workspace_procedures_over_qualified_builtins(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///shadow_package_builtin.tcl',
        'namespace eval json {\n'
        '    proc json2dict {value} {\n'
        '        return $value\n'
        '    }\n'
        '}\n'
        'json::json2dict payload\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    local_proc = next(
        proc for proc in facts.procedures if proc.qualified_name == '::json::json2dict'
    )
    resolution = next(
        candidate
        for candidate in analysis.resolutions
        if candidate.reference.kind == 'command' and candidate.reference.name == 'json::json2dict'
    )

    assert resolution.uncertainty.state == 'resolved'
    assert resolution.target_symbol_ids == (local_proc.symbol_id,)


def test_analysis_project_metadata_can_clear_bundled_builtin_annotations(
    parser: Parser,
    tmp_path: Path,
) -> None:
    override_path = tmp_path / 'override.meta.tcl'
    override_path.write_text(
        'meta module Tcl\nmeta command regexp {args}\n',
        encoding='utf-8',
    )
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(
        'proc run {} {\n    regexp {a} text match\n    puts $match\n}\n',
        encoding='utf-8',
    )

    _, analysis = _analyze_path(parser, source_path, metadata_paths=(tmp_path,))

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `match`.' in unresolved_messages


def test_analysis_project_metadata_can_replace_bundled_builtin_annotations(
    parser: Parser,
    tmp_path: Path,
) -> None:
    override_path = tmp_path / 'override.meta.tcl'
    override_path.write_text(
        'meta module Tcl\nmeta command regexp {args} {\n    bind 1 set\n}\n',
        encoding='utf-8',
    )
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(
        'proc run {} {\n    regexp destination text\n    puts $destination\n}\n',
        encoding='utf-8',
    )

    _, analysis = _analyze_path(parser, source_path, metadata_paths=(tmp_path,))

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `destination`.' not in unresolved_messages


def test_analysis_applies_sibling_metadata_to_tm_sources(
    parser: Parser,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / 'helper.tm'
    source_path.write_text(
        'proc copy_into {value name} {}\n'
        'proc run {} {\n'
        '    copy_into hello out\n'
        '    puts $out\n'
        '}\n',
        encoding='utf-8',
    )
    metadata_path = tmp_path / 'helper.meta.tcl'
    metadata_path.write_text(
        'meta command copy_into {value name} {\n    bind 2 set\n}\n',
        encoding='utf-8',
    )

    _, analysis = _analyze_path(parser, source_path, metadata_paths=(tmp_path,))

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `out`.' not in unresolved_messages


def test_analysis_does_not_guess_sibling_metadata_when_tcl_and_tm_both_exist(
    parser: Parser,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / 'helper.tcl'
    source_path.write_text(
        'proc copy_into {value name} {}\n'
        'proc run {} {\n'
        '    copy_into hello out\n'
        '    puts $out\n'
        '}\n',
        encoding='utf-8',
    )
    (tmp_path / 'helper.tm').write_text('proc unrelated {} {}\n', encoding='utf-8')
    metadata_path = tmp_path / 'helper.meta.tcl'
    metadata_path.write_text(
        'meta command copy_into {value name} {\n    bind 2 set\n}\n',
        encoding='utf-8',
    )

    _, analysis = _analyze_path(parser, source_path, metadata_paths=(tmp_path,))

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `out`.' in unresolved_messages


def test_analysis_later_metadata_roots_can_clear_sibling_bind_annotations(
    parser: Parser,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(
        'proc wrapper {x} {}\nproc use {} {\n    wrapper foo\n    puts $foo\n}\n',
        encoding='utf-8',
    )

    early_root = tmp_path / 'early'
    early_root.mkdir()
    (early_root / 'main.meta.tcl').write_text(
        'meta command wrapper {name} {\n    bind 1 set\n}\n',
        encoding='utf-8',
    )

    late_root = tmp_path / 'late'
    late_root.mkdir()
    (late_root / 'main.meta.tcl').write_text(
        'meta command wrapper {name}\n',
        encoding='utf-8',
    )

    _, analysis = _analyze_path(parser, source_path, metadata_paths=(early_root, late_root))

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `foo`.' in unresolved_messages


def test_analysis_applies_unqualified_sibling_metadata_effects_to_local_procedures(
    parser: Parser,
    tmp_path: Path,
) -> None:
    metadata_registry = create_metadata_registry((tmp_path,))
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    workspace = WorkspaceIndex()

    source_path = tmp_path / 'main.tcl'
    source_path.write_text(
        'proc wrapper {pkg} {}\nwrapper foo\n',
        encoding='utf-8',
    )
    (tmp_path / 'main.meta.tcl').write_text(
        'meta command wrapper {pkg} {\n    package select 1\n}\n',
        encoding='utf-8',
    )

    parse_result = parser.parse_document(
        source_path.as_uri(),
        source_path.read_text(encoding='utf-8'),
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)

    assert dependency_required_packages(
        source_path,
        facts,
        workspace,
        metadata_registry=metadata_registry,
    ) == frozenset({'foo'})


def test_analysis_later_metadata_roots_can_clear_sibling_metadata_effects(
    parser: Parser,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(
        'proc wrapper {script} {}\nwrapper {package require foo}\n',
        encoding='utf-8',
    )

    early_root = tmp_path / 'early'
    early_root.mkdir()
    (early_root / 'main.meta.tcl').write_text(
        'meta command ::wrapper {script} {\n    enter tcl body 1\n}\n',
        encoding='utf-8',
    )

    late_root = tmp_path / 'late'
    late_root.mkdir()
    (late_root / 'main.meta.tcl').write_text(
        'meta command ::wrapper {script}\n',
        encoding='utf-8',
    )

    metadata_registry = create_metadata_registry((early_root, late_root))
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    workspace = WorkspaceIndex()
    parse_result = parser.parse_document(
        source_path.as_uri(),
        source_path.read_text(encoding='utf-8'),
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)

    assert (
        dependency_required_packages(
            source_path,
            facts,
            workspace,
            metadata_registry=metadata_registry,
        )
        == frozenset()
    )


def test_analysis_keeps_option_aware_bindings_conservative_when_prefix_is_dynamic(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_regexp.tcl',
        'proc run {flag pattern} {\n'
        '    regexp $flag $pattern text result\n'
        '    puts $text\n'
        '    puts $result\n'
        '}\n',
    )
    analysis = snapshot.analysis

    unresolved_messages = {
        diagnostic.message
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    }
    assert 'Unresolved variable `text`.' in unresolved_messages
    assert 'Unresolved variable `result`.' in unresolved_messages
