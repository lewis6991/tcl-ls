from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.metadata_commands import load_metadata_commands
from tcl_lsp.parser import Parser

from .support import analyze_path


def test_metadata_dependency_and_alias_declarations_are_valid_tcl_commands(
    parser: Parser, tmp_path: Path
) -> None:
    source = tmp_path / 'example.meta.tcl'
    source.write_text(
        'meta alias tcl_trace trace\nmeta source {../source space/common.tcl}\n',
        encoding='utf-8',
    )

    _, analysis = analyze_path(parser, source)

    assert analysis.diagnostics == ()


def test_aliases_keep_subcommand_checks_and_variable_bindings(
    parser: Parser, tmp_path: Path
) -> None:
    (tmp_path / 'aliases.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta alias tcl_trace trace\n'
            '    meta alias match regexp\n'
            '    meta alias collect lappend\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'proc run {} {\n'
        '    match {(a)} a full part\n'
        '    collect values $part\n'
        '    puts $values\n'
        '    tcl_trace add execution run enter handler\n'
        '    tcl_trace add exection run enter handler\n'
        '    tcl_trace info execution\n'
        '}\n',
        encoding='utf-8',
    )

    _, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert sorted(d.code for d in analysis.diagnostics) == [
        'unknown-subcommand',
        'wrong-argument-count',
    ]


def test_aliases_reuse_the_original_declaration_plugin(parser: Parser, tmp_path: Path) -> None:
    (tmp_path / 'declare.tcl').write_text(
        'proc declare {words info} {\n'
        '    if {[dict get $info metadata-command] ne "original"} {return {}}\n'
        '    return {{procedure {\n'
        '        name select 2\n'
        '        params select 3 format tepam\n'
        '        body select 4\n'
        '    }}}\n'
        '}\n',
        encoding='utf-8',
    )
    (tmp_path / 'aliases.meta.tcl').write_text(
        (
            'meta module Tcl {\n'
            '    meta command original {name attributes body} {plugin declare.tcl declare}\n'
            '    meta alias declare original\n'
            '}\n'
        ),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text(
        'declare greet {-args {{name}}} {return $name}\ngreet World\n',
        encoding='utf-8',
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert {proc.qualified_name for proc in facts.procedures} == {'::greet'}
    assert analysis.diagnostics == ()


def test_alias_chains_follow_project_overrides(parser: Parser, tmp_path: Path) -> None:
    early = tmp_path / 'early'
    late = tmp_path / 'late'
    early.mkdir()
    late.mkdir()
    (early / 'commands.meta.tcl').write_text(
        ('meta module Tcl {\n    meta command tool {name}\n    meta alias first tool\n}\n'),
        encoding='utf-8',
    )
    (late / 'commands.meta.tcl').write_text(
        ('meta module Tcl {\n    meta command tool {name value}\n    meta alias second first\n}\n'),
        encoding='utf-8',
    )
    source = tmp_path / 'main.tcl'
    source.write_text('tool a b\nfirst a b\nsecond a b\nsecond a\n', encoding='utf-8')

    _, analysis = analyze_path(parser, source, metadata_paths=(early, late))

    assert [d.code for d in analysis.diagnostics] == ['wrong-argument-count']


@pytest.mark.parametrize(
    ('declarations', 'message'),
    [
        ('meta alias first missing\n', 'unknown target'),
        ('meta alias first second\nmeta alias second first\n', 'alias cycle'),
        ('meta alias first trace\nmeta command first {}\n', 'Conflicting metadata'),
    ],
)
def test_invalid_aliases_report_configuration_errors(
    tmp_path: Path, declarations: str, message: str
) -> None:
    metadata = tmp_path / 'aliases.meta.tcl'
    metadata.write_text(f'meta module Tcl {{\n{declarations}}}\n', encoding='utf-8')

    with pytest.raises(RuntimeError, match=message):
        load_metadata_commands(metadata)
