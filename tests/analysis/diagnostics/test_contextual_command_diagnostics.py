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


def _analyze_with_metadata_files(
    parser: Parser,
    tmp_path: Path,
    *,
    metadata_files: dict[str, str],
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    source_path = tmp_path / 'main.tcl'
    for file_name, metadata_text in metadata_files.items():
        (tmp_path / file_name).write_text(metadata_text, encoding='utf-8')
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


def _analyze_with_metadata_roots(
    parser: Parser,
    tmp_path: Path,
    *,
    metadata_roots: tuple[Path, ...],
    source_text: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(source_text, encoding='utf-8')

    metadata_registry = create_metadata_registry(metadata_roots)
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


def _command_calls_with_metadata_roots(
    parser: Parser,
    tmp_path: Path,
    *,
    metadata_roots: tuple[Path, ...],
    source_text: str,
) -> tuple[tuple[str | None, str | None], ...]:
    source_path = tmp_path / 'main.tcl'
    source_path.write_text(source_text, encoding='utf-8')

    metadata_registry = create_metadata_registry(metadata_roots)
    extractor = FactExtractor(parser, metadata_registry=metadata_registry)

    parse_result = parser.parse_document(source_path.as_uri(), source_text)
    facts = extractor.extract(parse_result)
    return tuple((call.name, call.embedded_language) for call in facts.command_calls)


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


def test_analysis_allows_tcl_when_language_extends_it(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    extends tcl\n'
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


def test_analysis_allows_tcl_when_any_repeated_language_definition_extends_it(
    parser: Parser,
    tmp_path: Path,
) -> None:
    metadata_cases = (
        {
            'a.meta.tcl': (
                'meta module Tcl\n'
                'meta language sample {\n'
                '    extends tcl\n'
                '    command local {name}\n'
                '}\n'
                'meta command wrapper {script} {\n'
                '    enter sample body 1\n'
                '}\n'
            ),
            'b.meta.tcl': ('meta module Tcl\nmeta language sample {\n    command step {name}\n}\n'),
        },
        {
            'a.meta.tcl': (
                'meta module Tcl\n'
                'meta language sample {\n'
                '    command step {name}\n'
                '}\n'
                'meta command wrapper {script} {\n'
                '    enter sample body 1\n'
                '}\n'
            ),
            'b.meta.tcl': (
                'meta module Tcl\n'
                'meta language sample {\n'
                '    extends tcl\n'
                '    command local {name}\n'
                '}\n'
            ),
        },
    )

    for index, metadata_files in enumerate(metadata_cases):
        case_tmp_path = tmp_path / f'case-{index}'
        case_tmp_path.mkdir()
        codes, messages = _analyze_with_metadata_files(
            parser,
            case_tmp_path,
            metadata_files=metadata_files,
            source_text='wrapper {set foo bar}\n',
        )

        assert codes == ()
        assert messages == ()


def test_analysis_later_metadata_root_can_close_language_again(
    parser: Parser,
    tmp_path: Path,
) -> None:
    early_root = tmp_path / 'early'
    late_root = tmp_path / 'late'
    early_root.mkdir()
    late_root.mkdir()
    (early_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\n'
        'meta language sample {\n'
        '    extends tcl\n'
        '}\n'
        'meta command wrapper {script} {\n'
        '    enter sample body 1\n'
        '}\n',
        encoding='utf-8',
    )
    (late_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\nmeta language sample {\n}\n',
        encoding='utf-8',
    )

    codes, messages = _analyze_with_metadata_roots(
        parser,
        tmp_path,
        metadata_roots=(early_root, late_root),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ('unresolved-command',)
    assert messages == ('Unresolved command `set`.',)


def test_analysis_later_metadata_root_can_open_language_to_tcl(
    parser: Parser,
    tmp_path: Path,
) -> None:
    early_root = tmp_path / 'early'
    late_root = tmp_path / 'late'
    early_root.mkdir()
    late_root.mkdir()
    (early_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\n'
        'meta language sample {\n'
        '}\n'
        'meta command wrapper {script} {\n'
        '    enter sample body 1\n'
        '}\n',
        encoding='utf-8',
    )
    (late_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\nmeta language sample {\n    extends tcl\n}\n',
        encoding='utf-8',
    )

    codes, messages = _analyze_with_metadata_roots(
        parser,
        tmp_path,
        metadata_roots=(early_root, late_root),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ()
    assert messages == ()


def test_analysis_later_metadata_root_replaces_top_level_enter_command_tree(
    parser: Parser,
    tmp_path: Path,
) -> None:
    early_root = tmp_path / 'early'
    late_root = tmp_path / 'late'
    early_root.mkdir()
    late_root.mkdir()
    (early_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\n'
        'meta language sample {\n'
        '    extends tcl\n'
        '}\n'
        'meta command wrapper {script} {\n'
        '    enter sample body 1\n'
        '}\n',
        encoding='utf-8',
    )
    (late_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\nmeta command wrapper {script}\n',
        encoding='utf-8',
    )

    command_calls = _command_calls_with_metadata_roots(
        parser,
        tmp_path,
        metadata_roots=(early_root, late_root),
        source_text='wrapper {set foo bar}\n',
    )

    assert command_calls == (('wrapper', None),)


def test_analysis_later_metadata_root_replaces_contextual_command_shape(
    parser: Parser,
    tmp_path: Path,
) -> None:
    early_root = tmp_path / 'early'
    late_root = tmp_path / 'late'
    early_root.mkdir()
    late_root.mkdir()
    (early_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\n'
        'meta language sample {\n'
        '    command local {name}\n'
        '}\n'
        'meta command wrapper {script} {\n'
        '    enter sample body 1\n'
        '}\n',
        encoding='utf-8',
    )
    (late_root / 'sample.meta.tcl').write_text(
        'meta module Tcl\nmeta language sample {\n    command local {name value}\n}\n',
        encoding='utf-8',
    )

    codes, messages = _analyze_with_metadata_roots(
        parser,
        tmp_path,
        metadata_roots=(early_root, late_root),
        source_text='wrapper {local x}\n',
    )

    assert codes == ('wrong-argument-count',)
    assert messages == ('Wrong number of arguments for command `local`; expected 2, got 1.',)


def test_analysis_does_not_fall_back_to_tcl_in_empty_embedded_language(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ('unresolved-command',)
    assert messages == ('Unresolved command `set`.',)


def test_analysis_allows_tcl_in_empty_language_that_extends_it(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    extends tcl\n'
            '}\n'
            'meta command wrapper {script} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ()
    assert messages == ()


def test_analysis_does_not_fall_back_to_tcl_for_undefined_embedded_language(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\nmeta command wrapper {script} {\n    enter missing body 1\n}\n'
        ),
        source_text='wrapper {set foo bar}\n',
    )

    assert codes == ('unresolved-command',)
    assert messages == ('Unresolved command `set`.',)


def test_analysis_handles_multiple_enter_clauses(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command known {x}\n'
            '}\n'
            'meta command double {left right} {\n'
            '    enter sample body 1\n'
            '    enter sample body 2\n'
            '}\n'
        ),
        source_text='double {known ok} {unknown_cmd bad}\n',
    )

    assert codes == ('unresolved-command',)
    assert messages == ('Unresolved command `unknown_cmd`.',)


def test_analysis_applies_static_enter_to_special_proc_body(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command local {name}\n'
            '}\n'
            'meta command proc {name params body} {\n'
            '    enter sample body 3\n'
            '}\n'
        ),
        source_text='proc demo {} {local x}\n',
    )

    assert codes == ()
    assert messages == ()


def test_analysis_allows_valid_special_enter_for_dynamic_proc_body(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command local {name}\n'
            '}\n'
            'meta command proc {name params body} {\n'
            '    enter sample body 3\n'
            '}\n'
        ),
        source_text='proc demo {} [list local x]\n',
    )

    assert codes == ()
    assert messages == ()


def test_analysis_applies_plugin_enter_to_special_proc_body(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata_files(
        parser,
        tmp_path,
        metadata_files={
            'sample.meta.tcl': (
                'meta module Tcl\n'
                'meta language sample {\n'
                '    command local {name}\n'
                '}\n'
                'meta command proc {name params body} {\n'
                '    plugin plugin.tcl emit\n'
                '}\n'
            ),
            'plugin.tcl': (
                'proc emit {words info} {\n    return [list [list enter sample body 4]]\n}\n'
            ),
        },
        source_text='proc demo {} {local x}\n',
    )

    assert codes == ()
    assert messages == ()


def test_analysis_rejects_inline_enter_ranges_on_special_commands(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command local {name}\n'
            '}\n'
            'meta command for {start test next body} {\n'
            '    enter sample body 1..4\n'
            '}\n'
        ),
        source_text='for {local start} 1 {local next} {local body}\n',
    )

    assert codes == ('unsupported-special-enter',)
    assert messages == (
        'Structured Tcl commands only support single-word `enter body` selectors '
        'for script-body arguments.',
    )


def test_analysis_rejects_non_body_enter_targets_on_special_commands(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command local {name}\n'
            '}\n'
            'meta command while {test body} {\n'
            '    enter sample body 1\n'
            '}\n'
        ),
        source_text='while {local x} {set ready 1}\n',
    )

    assert codes == ('unsupported-special-enter',)
    assert messages == (
        'Structured Tcl commands only support single-word `enter body` selectors '
        'for script-body arguments.',
    )


def test_analysis_rejects_plugin_inline_enter_ranges_on_special_commands(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata_files(
        parser,
        tmp_path,
        metadata_files={
            'sample.meta.tcl': (
                'meta module Tcl\n'
                'meta language sample {\n'
                '    command local {name}\n'
                '}\n'
                'meta command for {start test next body} {\n'
                '    plugin plugin.tcl emit\n'
                '}\n'
            ),
            'plugin.tcl': (
                'proc emit {words info} {\n    return [list [list enter sample body 1..4]]\n}\n'
            ),
        },
        source_text='for {local start} 1 {local next} {local body}\n',
    )

    assert codes == ('unsupported-special-enter',)
    assert messages == (
        'Structured Tcl commands only support single-word `enter body` selectors '
        'for script-body arguments.',
    )


def test_analysis_reports_overlapping_enter_ranges_on_special_command(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language one {\n'
            '    command first {x}\n'
            '}\n'
            'meta language two {\n'
            '    command second {x}\n'
            '}\n'
            'meta command proc {name params body} {\n'
            '    enter one body 3\n'
            '    enter two body 3\n'
            '}\n'
        ),
        source_text='proc demo {} {first ok}\n',
    )

    assert codes == ('conflicting-embedded-language',)
    assert messages == ('Overlapping enter body selections are ambiguous.',)


def test_analysis_reports_overlapping_enter_ranges(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language one {\n'
            '    command first {x}\n'
            '}\n'
            'meta language two {\n'
            '    command second {x}\n'
            '}\n'
            'meta command wrapper {a b c} {\n'
            '    enter one body 1..2\n'
            '    enter two body 2..3\n'
            '}\n'
        ),
        source_text='wrapper {first ok} {unknown_cmd bad} {second ok}\n',
    )

    assert codes == ('conflicting-embedded-language',)
    assert messages == ('Overlapping enter body selections are ambiguous.',)


def test_analysis_reports_overlapping_enter_ranges_in_same_language(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata(
        parser,
        tmp_path,
        metadata_text=(
            'meta module Tcl\n'
            'meta language sample {\n'
            '    command first {x}\n'
            '}\n'
            'meta command wrapper {a b} {\n'
            '    enter sample body 1\n'
            '    enter sample body 1..2\n'
            '}\n'
        ),
        source_text='wrapper {first ok} second\n',
    )

    assert codes == ('conflicting-embedded-language',)
    assert messages == ('Overlapping enter body selections are ambiguous.',)


def test_analysis_reports_overlapping_plugin_and_contextual_enter_ranges(
    parser: Parser,
    tmp_path: Path,
) -> None:
    codes, messages = _analyze_with_metadata_files(
        parser,
        tmp_path,
        metadata_files={
            'sample.meta.tcl': (
                'meta module Tcl\n'
                'meta language outer {\n'
                '    command builder {left right} {\n'
                '        enter one body 1\n'
                '        plugin plugin.tcl emit\n'
                '    }\n'
                '}\n'
                'meta language one {\n'
                '    command first {x}\n'
                '}\n'
                'meta language two {\n'
                '    command second {x}\n'
                '}\n'
                'meta command wrapper {script} {\n'
                '    enter outer body 1\n'
                '}\n'
            ),
            'plugin.tcl': (
                'proc emit {words info} {\n    return [list [list enter two body 2..3]]\n}\n'
            ),
        },
        source_text='wrapper {builder {first ok} {second ok}}\n',
    )

    assert codes == ('conflicting-embedded-language',)
    assert messages == ('Overlapping enter body selections are ambiguous.',)
