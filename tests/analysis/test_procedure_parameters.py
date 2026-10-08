from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.parser import Parser

from .support import analyze_path


@pytest.mark.parametrize(
    ('parameter_format', 'parameters'),
    [
        (
            'tepam',
            '-description \\\n "Example" -args\\\n'
            ' {{-target -default $fallback} {items -multiple}}',
        ),
        ('tepam-args', '-target items'),
    ],
)
def test_tepam_wrappers_bind_parameters_at_their_source_locations(
    parser: Parser, tmp_path: Path, parameter_format: str, parameters: str
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        'meta module Tcl\n'
        'meta command declare {name attributes body} {\n'
        '    procedure {\n'
        '        name select 1\n'
        f'        params select 2 format {parameter_format}\n'
        '        body select 3\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )
    text = (
        f'declare run {{{parameters}}} {{\n'
        '    puts [list $target $items $missing]\n'
        '}\n'
        'run -target example first second\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text(text, encoding='utf-8')

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert procedure.qualified_name == '::run'
    assert procedure.arity is None
    assert [parameter.name for parameter in procedure.parameters] == ['target', 'items']
    for parameter in procedure.parameters:
        assert parameter.span.start.offset == text.index(parameter.name)
        assert text[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
    assert [(d.code, d.message) for d in analysis.diagnostics] == [
        ('unresolved-variable', 'Unresolved variable `missing`.'),
    ]


@pytest.mark.parametrize(
    'header',
    ['$header', '{-args}', '{-args "\\{"}', '{-args {{value}suffix}}', '{*}{-args {{value}}}'],
)
def test_unreadable_tepam_headers_do_not_invent_procedures(
    parser: Parser, tmp_path: Path, header: str
) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text(
        'package require tepam\n'
        f'proc declare {{header}} {{tepam::procedure run {header} {{puts $value}}}}\n',
        encoding='utf-8',
    )

    facts, _ = analyze_path(parser, source)

    assert [procedure.qualified_name for procedure in facts.procedures] == ['::declare']
