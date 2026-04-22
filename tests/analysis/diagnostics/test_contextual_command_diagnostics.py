from __future__ import annotations

from pathlib import Path

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.metadata_paths import create_metadata_registry
from tcl_lsp.parser import Parser

from ..support import analyze_document as _analyze


def _analyze_with_metadata(
    parser: Parser,
    tmp_path: Path,
    *,
    metadata_text: str,
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    metadata_path = tmp_path / 'sample.meta.tcl'
    source_path = tmp_path / 'main.tcl'
    metadata_path.write_text(metadata_text, encoding='utf-8')
    source_path.write_text(source_text, encoding='utf-8')

    metadata_registry = create_metadata_registry((tmp_path,))
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)
    resolver = Resolver(metadata_registry=metadata_registry)
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(source_path.as_uri(), source_text)
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)
    return (
        tuple(diagnostic.code for diagnostic in analysis.diagnostics),
        tuple(diagnostic.message for diagnostic in analysis.diagnostics),
    )


def test_analysis_reports_unknown_subcommand_in_contextual_command_tree(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command root variants {\n'
            '        form {subcommand args}\n'
            '        command child variants {\n'
            '            form {name}\n'
            '            form {name value}\n'
            '        }\n'
            '        command opt {args} {\n'
            '            option -flag\n'
            '            option -value value\n'
            '        }\n'
            '    }\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {root gurka value}\n',
    )

    assert codes == ('unknown-subcommand',)
    assert messages == ('Unknown subcommand `gurka` for command `root`.',)


def test_analysis_reports_wrong_argument_count_for_contextual_subcommand(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command root variants {\n'
            '        form {subcommand args}\n'
            '        command child variants {\n'
            '            form {name}\n'
            '            form {name value}\n'
            '        }\n'
            '    }\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {root child}\n',
    )

    assert codes == ('wrong-argument-count',)
    assert messages == (
        'Wrong number of arguments for command `root child`; expected 1 or 2, got 0.',
    )


def test_analysis_reports_unknown_option_for_contextual_command(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command root variants {\n'
            '        form {subcommand args}\n'
            '        command opt {args} {\n'
            '            option -flag\n'
            '            option -value value\n'
            '        }\n'
            '    }\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {root opt -bogus value}\n',
    )

    assert codes == ('unknown-option',)
    assert messages == ('Unknown option `-bogus` for command `root opt`.',)


def test_analysis_reports_unresolved_command_in_meta_body_via_helper_language(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command interp {subcommand args} {\n    ommand alias {srcPath srcToken}\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'unresolved-command'
    ]
    assert snapshot.analysis.diagnostics[0].message == 'Unresolved command `ommand`.'


def test_analysis_does_not_fall_back_to_tcl_in_closed_meta_helper_language(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command demo {args} {\n    set foo bar\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'unresolved-command'
    ]
    assert snapshot.analysis.diagnostics[0].message == 'Unresolved command `set`.'


def test_analysis_reports_wrong_argument_count_in_meta_command_body(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command demo {args} {\n    option\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'wrong-argument-count'
    ]
    assert snapshot.analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `option`; expected 1 or 2, got 0.'
    )


def test_analysis_reports_wrong_argument_count_for_structured_helper_selector_clauses(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command demo {args} {\n    package select\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'wrong-argument-count'
    ]
    assert snapshot.analysis.diagnostics[0].message == (
        'Wrong number of arguments for command `package`; expected 2 or 2..6, got 1.'
    )


def test_analysis_reports_invalid_arguments_for_meta_command_shell(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command interp hello {}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'invalid-arguments'
    ]
    assert snapshot.analysis.diagnostics[0].message == (
        'Invalid arguments for command `meta command`; expected one of: '
        '`meta command {name shape body}`, or `meta command {name variants body}`.'
    )


def test_analysis_reports_invalid_arguments_for_nested_meta_command_shell(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///demo.meta.tcl',
        'meta command interp {subcommand args} {\n    command child hello {}\n}\n',
    )

    assert [diagnostic.code for diagnostic in snapshot.analysis.diagnostics] == [
        'invalid-arguments'
    ]
    assert snapshot.analysis.diagnostics[0].message == (
        'Invalid arguments for command `command`; expected one of: '
        '`command {name shape body}`, or `command {name variants body}`.'
    )


def test_analysis_allows_tcl_fallback_when_language_declares_it(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    fallback tcl\n'
            '    command local {name}\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ()
    assert messages == ()
