from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.parser import Parser

from .support import analyze_path


@pytest.mark.parametrize(
    ('namespace', 'call'),
    [('sample', 'declare'), ('sample', '::sample::declare'), ('::', 'sample::declare')],
)
def test_metadata_declarations_resolve_relative_to_the_current_namespace(
    parser: Parser, tmp_path: Path, namespace: str, call: str
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command sample::declare {name params body} {\n'
            '        procedure {name select 1; params select 2; body select 3}\n'
            '    }\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        f'namespace eval {namespace} {{\n'
        f'    {call} greet {{name}} {{puts $name}}\n'
        '    greet world\n'
        '}\n',
        encoding='utf-8',
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    expected_name = '::greet' if namespace == '::' else '::sample::greet'
    assert {proc.qualified_name for proc in facts.procedures} == {expected_name}
    assert analysis.diagnostics == ()


def test_namespaced_metadata_checks_bodies_and_binds_local_variables(
    parser: Parser, tmp_path: Path
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command sample::tools::with_value {name body} {\n'
            '        bind 1 set\n'
            '        enter tcl body 2\n'
            '    }\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'namespace eval sample {proc run {} {\n'
        '    tools::with_value value {puts $value; puts $missing}\n'
        '}}\n',
        encoding='utf-8',
    )

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert [(d.code, d.message) for d in analysis.diagnostics] == [
        ('unresolved-variable', 'Unresolved variable `missing`.'),
    ]


def test_current_namespace_metadata_takes_precedence_over_global_metadata(
    parser: Parser, tmp_path: Path
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command copy {name value} {bind 1 set}\n'
            '    meta command sample::copy {value name} {bind 2 set}\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'namespace eval sample {proc run {} {\n'
        '    copy ignored local\n'
        '    ::copy global ignored\n'
        '    puts $local\n'
        '    puts $global\n'
        '    puts $ignored\n'
        '}}\n',
        encoding='utf-8',
    )

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert [(d.code, d.message) for d in analysis.diagnostics] == [
        ('unresolved-variable', 'Unresolved variable `ignored`.'),
    ]


def test_namespaced_metadata_resolves_subcommands(parser: Parser, tmp_path: Path) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command sample::api {subcommand args} {\n'
            '        command bind {name} {bind 1 set}\n'
            '    }\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text('namespace eval sample {api bind value; puts $value}\n', encoding='utf-8')

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert analysis.diagnostics == ()


def test_metadata_does_not_search_parent_namespaces(parser: Parser, tmp_path: Path) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        ('meta module Tcl {\n    meta command sample::copy {name} {bind 1 set}\n}\n'),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'namespace eval sample::child {copy value}\nnamespace eval sample {::copy value}\n',
        encoding='utf-8',
    )

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert [d.code for d in analysis.diagnostics] == ['unresolved-command', 'unresolved-command']


def test_local_command_metadata_does_not_use_global_subcommands(
    parser: Parser, tmp_path: Path
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command api {subcommand args} {\n'
            '        command bind {name} {bind 1 set}\n'
            '    }\n'
            '    meta command sample::api {name value} {bind 1 set}\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'proc sample::run {} {api bind value; puts $bind; puts $value}\n', encoding='utf-8'
    )

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert [(d.code, d.message) for d in analysis.diagnostics] == [
        ('unresolved-variable', 'Unresolved variable `value`.'),
    ]
