from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.parser import Parser
from tests.plugin_support import write_header_plugin

from .support import analyze_path


def _write_wrapper_metadata(tmp_path: Path, parameter_parser: str) -> None:
    if parameter_parser != 'tcl':
        hook = {
            'tepam': 'header_parameters',
            'tepam-args': 'implementation',
            'shared_header': 'shared',
        }[parameter_parser]
        write_header_plugin(tmp_path, hook=hook, metadata_name='custom.meta.tcl')
        return
    (tmp_path / 'custom.meta.tcl').write_text(
        'meta module Tcl {\n'
        '    meta command declare {name params body} {\n'
        '        procedure {name {select 1}; params {select 2}; body {select 3}}\n'
        '    }\n'
        '}\n',
        encoding='utf-8',
    )


@pytest.mark.parametrize('declaration', ['proc', 'declare'])
@pytest.mark.parametrize('argument', ['$common_args', '"$common_args"'])
def test_procedure_parameter_words_resolve_known_tcl_values(
    parser: Parser, tmp_path: Path, declaration: str, argument: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'tcl')
    text = (
        'set common_args {bg engines}\n'
        f'{declaration} prove {argument} {{puts [list $bg $engines $missing]}}\n'
        'prove true\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text(text, encoding='utf-8')

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['bg', 'engines']
    for parameter in procedure.parameters:
        assert parameter.span.start.offset == text.index(parameter.name)
        assert text[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
    assert {d.code for d in analysis.diagnostics} == {'unresolved-variable', 'wrong-argument-count'}
    assert [d.message for d in analysis.diagnostics if d.code == 'unresolved-variable'] == [
        'Unresolved variable `missing`.'
    ]


def test_braced_proc_parameters_keep_variable_references_literal(
    parser: Parser, tmp_path: Path
) -> None:
    source = tmp_path / 'main.tcl'
    source.write_text('set common_args {bg engines}\nproc prove {$common_args} {puts $bg}\n')

    facts, analysis = analyze_path(parser, source)

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['$common_args']
    assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `bg`.']


@pytest.mark.parametrize('declaration', ['proc', 'declare'])
@pytest.mark.parametrize('separator', ['\\t', '\\\n '])
def test_static_parameter_words_keep_support_for_decoded_escapes(
    parser: Parser, tmp_path: Path, declaration: str, separator: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'tcl')
    source = tmp_path / 'main.tcl'
    source.write_text(f'{declaration} prove "bg{separator}engines" {{puts [list $bg $engines]}}\n')

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['bg', 'engines']
    assert analysis.diagnostics == ()


@pytest.mark.parametrize('declaration', ['proc', 'declare'])
def test_resolving_a_parameter_word_does_not_substitute_its_value_again(
    parser: Parser, tmp_path: Path, declaration: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'tcl')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'set nested {bg engines}\n'
        'set common_args {$nested}\n'
        f'{declaration} prove $common_args {{puts $bg}}\n'
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['$nested']
    assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `bg`.']


@pytest.mark.parametrize('parameter_parser', ['tepam', 'tepam-args', 'shared_header'])
def test_tepam_parameter_words_resolve_known_values_without_wrapper_substitution(
    parser: Parser, tmp_path: Path, parameter_parser: str
) -> None:
    _write_wrapper_metadata(tmp_path, parameter_parser)
    parameters = '{-bg -type none} {-engines -optional}'
    if parameter_parser in {'tepam', 'shared_header'}:
        parameters = '-args {' + parameters + '}'
    source = tmp_path / 'main.tcl'
    source.write_text(
        f'set common_args {{{parameters}}}\n'
        'set alias $common_args\n'
        'declare prove $alias {puts [list $bg $engines]}\n'
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['bg', 'engines']
    assert analysis.diagnostics == ()


@pytest.mark.parametrize(
    ('parameter_parser', 'parameters'),
    [
        (
            'tepam',
            '-description \\\n "Example" -args\\\n'
            ' {{-target -default $fallback} {items -multiple}}',
        ),
        ('tepam-args', '-target items'),
        ('shared_header', '-args {{-target -default $fallback} {items -multiple}}'),
    ],
)
def test_tepam_wrappers_bind_parameters_at_their_source_locations(
    parser: Parser, tmp_path: Path, parameter_parser: str, parameters: str
) -> None:
    _write_wrapper_metadata(tmp_path, parameter_parser)
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


@pytest.mark.parametrize(
    'argument_list',
    [
        '{$common {-flow -default auto}}',
        '$common',
        '${common}',
        '{$::project::common {-flow -default auto}}',
        '${::project::common}',
    ],
)
def test_shared_header_headers_bind_shared_parameters(
    parser: Parser, tmp_path: Path, argument_list: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'shared_header')
    text = (
        'namespace eval project {\n'
        '    set common {{-props -default .*} {-engines -optional} {-bg -type none}}\n'
        f'    declare prove {{-args {argument_list}}} {{\n'
        '        foreach option {props engines} {\n'
        '            if {[info exists $option]} {puts [subst \\$$option]}\n'
        '        }\n'
        '        if {$bg} {puts background}\n'
        '        puts $missing\n'
        '    }\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text(text, encoding='utf-8')

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert procedure.qualified_name == '::project::prove'
    expected = ['props', 'engines', 'bg']
    if 'flow' in argument_list:
        expected.append('flow')
    assert [parameter.name for parameter in procedure.parameters] == expected
    for parameter in procedure.parameters:
        assert parameter.span.start.offset == text.index(parameter.name)
        assert text[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
    assert [(d.code, d.message) for d in analysis.diagnostics] == [
        ('unresolved-variable', 'Unresolved variable `missing`.'),
    ]


@pytest.mark.parametrize('parameter_parser', ['tepam', 'shared_header'])
def test_only_shared_header_plugin_expands_argument_fragments(
    parser: Parser, tmp_path: Path, parameter_parser: str
) -> None:
    _write_wrapper_metadata(tmp_path, parameter_parser)
    source = tmp_path / 'main.tcl'
    source.write_text(
        'set common {{-props -default .*}}\n'
        'set alias $common\n'
        'declare prove {-args {$alias {-bg -type none}}} {puts [list $props $bg]}\n'
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    if parameter_parser == 'shared_header':
        assert [p.name for p in procedure.parameters] == ['props', 'bg']
        assert analysis.diagnostics == ()
    else:
        assert [p.name for p in procedure.parameters] == ['bg']
        assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `props`.']


@pytest.mark.parametrize(
    'before',
    [
        '',
        'set common [read stdin]\n',
        'set common {{-props}}\nunset common\n',
        'set common {{-props}}\nlappend common {-engines}\n',
        'set common {{-props}}\neval [read stdin]\n',
        'if {[read stdin]} {set common {{-props}}} else {set common {{-engines}}}\n',
        'set common {\\{}\n',
    ],
)
def test_unknown_or_changed_fragments_do_not_invent_parameters(
    parser: Parser, tmp_path: Path, before: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'shared_header')
    source = tmp_path / 'main.tcl'
    source.write_text(before + 'declare prove {-args {$common}} {puts $props}\n')

    facts, _ = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert facts.procedures == ()


def test_fragment_expansion_does_not_substitute_a_second_time(
    parser: Parser, tmp_path: Path
) -> None:
    _write_wrapper_metadata(tmp_path, 'shared_header')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'set nested {{-props}}\n'
        'set common {$nested {-bg -type none}}\n'
        'declare prove {-args {$common}} {puts [list $props $bg]}\n'
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert [p.name for p in procedure.parameters] == ['bg']
    assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `props`.']


@pytest.mark.parametrize(
    'fragment',
    ['$common-suffix', '$common${other}', '$common[error]', '${common}suffix', '$project:common'],
)
def test_wrapper_plugin_does_not_expand_partial_variable_fragments(
    parser: Parser, tmp_path: Path, fragment: str
) -> None:
    _write_wrapper_metadata(tmp_path, 'shared_header')
    source = tmp_path / 'main.tcl'
    source.write_text(
        f'set common {{{{-props}}}}\ndeclare prove {{-args {{{fragment}}}}} {{puts $props}}\n'
    )

    facts, _ = analyze_path(parser, source, metadata_paths=(tmp_path,))

    assert facts.procedures == ()


def test_shared_header_headers_leave_command_substitutions_literal(
    parser: Parser, tmp_path: Path
) -> None:
    _write_wrapper_metadata(tmp_path, 'shared_header')
    source = tmp_path / 'main.tcl'
    source.write_text(
        'proc common_args {mode} {return {{-props}}}\n'
        'declare prove {-args {[common_args sec] {-bg -type none}}} '
        '{puts [list $props $bg]}\n'
    )

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    procedure = next(p for p in facts.procedures if p.qualified_name == '::prove')
    assert [p.name for p in procedure.parameters] == ['bg']
    assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `props`.']
