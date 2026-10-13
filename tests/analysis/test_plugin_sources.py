from __future__ import annotations

from pathlib import Path

import pytest

from tcl_lsp.analysis.facts.parsing import ListItem
from tcl_lsp.analysis.metadata_commands import MetadataBind, MetadataPlugin
from tcl_lsp.common import Position, Span
from tcl_lsp.parser import Parser
from tcl_lsp.plugins.host import TclPluginHost
from tcl_lsp.plugins.sources import PluginSources

from .support import analyze_path


def test_project_plugin_parses_custom_parameters_at_the_original_locations(
    parser: Parser, tmp_path: Path
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        'meta module Tcl {\n'
        '    meta command declare {args} {\n'
        '        command procedure {fields body name} {\n'
        '            procedure {\n'
        '                name {select 3}\n'
        '                params {select 1 plugin {fields.tcl fields}}\n'
        '                body {select 2}\n'
        '            }\n'
        '        }\n'
        '    }\n'
        '}\n'
    )
    (tmp_path / 'fields.tcl').write_text(
        'proc fields {source info} {\n'
        '    set text [dict get $source text]\n'
        '    if {![regexp {^[a-z]+(,[a-z]+)*$} $text]} {return {}}\n'
        '    set parameters {}\n'
        '    foreach range [regexp -all -inline -indices {[a-z]+} $text] {\n'
        '        lassign $range start end\n'
        '        set name [::tcl_lsp::slice $source $start [expr {$end + 1}]]\n'
        '        lappend parameters [dict get $name id]\n'
        '    }\n'
        '    return [list items $parameters]\n'
        '}\n'
    )
    text = (
        'namespace eval example {\n'
        '    set common {target,mode}\n'
        '    set alias $common\n'
        '    declare procedure $alias {puts [list $target $mode $missing]} run\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text(text)

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    (procedure,) = facts.procedures
    assert procedure.qualified_name == '::example::run'
    assert procedure.arity is None
    assert [parameter.name for parameter in procedure.parameters] == ['target', 'mode']
    for parameter in procedure.parameters:
        assert parameter.span.start.offset == text.index(parameter.name)
        assert text[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
    assert [diagnostic.message for diagnostic in analysis.diagnostics] == [
        'Unresolved variable `missing`.'
    ]


def test_plugin_queries_preserve_unicode_and_tcl_data_without_evaluation(tmp_path: Path) -> None:
    name = 'a {b}\\c'
    text = 'héllo 😀 {$unknown} [error nope]\n\\literal'
    start = Position(0, 0, 0)
    source = ListItem(text, Span(start, start.advance(text)), start)
    queries: list[str] = []

    def variable_source(requested: str) -> ListItem | None:
        queries.append(requested)
        return source if requested == name else None

    script = tmp_path / 'echo.tcl'
    script.write_text(
        'proc echo {words info} {\n'
        '    set value [::tcl_lsp::variable [lindex $words 1]]\n'
        '    if {[dict get $value text] ne [lindex $words 2]} {error "Changed value"}\n'
        '    return {{bind 2 set}}\n'
        '}\n'
    )
    host = TclPluginHost()
    try:
        (effect,) = host.call_plugin(
            MetadataPlugin(script, 'echo'),
            words=('declare', name, text),
            info={},
            sources=PluginSources(word_source=lambda _: None, variable_source=variable_source),
        )
    finally:
        host.close()

    assert isinstance(effect, MetadataBind)
    assert effect.kind == 'set'
    assert queries == [name]


@pytest.mark.parametrize(
    ('argument', 'declared'), [('empty', True), ('unknown', False), ('"em\\pty"', False)]
)
def test_parameter_parser_distinguishes_empty_and_unknown_declarations(
    parser: Parser, tmp_path: Path, argument: str, declared: bool
) -> None:
    (tmp_path / 'custom.meta.tcl').write_text(
        'meta module Tcl {meta command declare {name fields body} {\n'
        '    procedure {name {select 1}; params {select 2 plugin {fields.tcl fields}}; '
        'body {select 3}}\n'
        '}}\n'
    )
    (tmp_path / 'fields.tcl').write_text(
        'proc fields {value info} {\n'
        '    if {[dict get $value text] eq "unknown"} {return {}}\n'
        '    return {items {}}\n'
        '}\n'
    )
    source = tmp_path / 'main.tcl'
    source.write_text(f'declare run {argument} {{puts $missing}}\n')

    facts, analysis = analyze_path(parser, source, metadata_paths=(tmp_path,))

    if not declared:
        assert facts.procedures == ()
        assert analysis.diagnostics == ()
    else:
        (procedure,) = facts.procedures
        assert procedure.parameters == ()
        assert [d.message for d in analysis.diagnostics] == ['Unresolved variable `missing`.']


@pytest.mark.parametrize(
    ('result', 'message'),
    [
        ('items {invented}', 'Unknown plugin source `invented`'),
        ('names {}', 'Parameter parsers must return'),
        ('items {} items {}', 'Parameter parsers must return'),
    ],
)
def test_parameter_parser_rejects_invalid_results(
    tmp_path: Path, result: str, message: str
) -> None:
    script = tmp_path / 'invalid.tcl'
    script.write_text(f'proc invalid {{value info}} {{return {{{result}}}}}\n')
    start = Position(0, 0, 0)
    source = ListItem('input', Span(start, start.advance('input')), start)
    host = TclPluginHost()
    try:
        with pytest.raises(RuntimeError, match=message):
            host.call_parameter_parser(
                MetadataPlugin(script, 'invalid'),
                value=source,
                info={},
                sources=PluginSources(word_source=lambda _: None, variable_source=lambda _: None),
            )
    finally:
        host.close()


def test_plugin_cannot_invent_parameter_source_locations(tmp_path: Path) -> None:
    script = tmp_path / 'invalid.tcl'
    script.write_text(
        'proc invalid {words info} {\n'
        '    return {{procedure {name {select 2}; params {items {invented}}}}}\n'
        '}\n'
    )
    host = TclPluginHost()
    try:
        with pytest.raises(RuntimeError, match='Unknown plugin source `invented`'):
            host.call_plugin(
                MetadataPlugin(script, 'invalid'),
                words=('declare', 'run'),
                info={},
                sources=PluginSources(word_source=lambda _: None, variable_source=lambda _: None),
            )
    finally:
        host.close()
