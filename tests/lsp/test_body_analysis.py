from pathlib import Path

import pytest
from lsprotocol import types

from tcl_lsp.lsp import LanguageServer
from tests.lsp_support import process_message
from tests.plugin_support import write_header_plugin


def new_server() -> LanguageServer:
    server = LanguageServer()
    process_message(
        server,
        {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'capabilities': {}}},
    )
    return server


def assert_fresh_analysis(server: LanguageServer, uri: str, text: str) -> None:
    fresh = new_server()
    try:
        fresh.open_document(uri, text, 1)
        for active in (server, fresh):
            active.workspace.put_text_document(
                types.TextDocumentItem(
                    uri=uri,
                    language_id='tcl',
                    text=text,
                    version=active.documents[uri].version,
                )
            )
        tokens = server.semantic_tokens(uri)
        fresh_tokens = fresh.semantic_tokens(uri)
        assert tokens is not None and fresh_tokens is not None
        assert tokens.data == fresh_tokens.data
        actual = server.documents[uri]
        expected = fresh.documents[uri]
        assert actual.facts == expected.facts
        assert actual.analysis == expected.analysis
    finally:
        fresh.shutdown()


def test_body_edits_reuse_other_procedures_and_move_their_locations(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """proc first {} {puts unchanged}
proc edited {} {puts original}
proc last {arg} {
    global shared
    variable state
    set shared $arg
    set state $shared
    proc nested {n} {return $n}
    # tcl-ls: diagnostic statement unresolved-command off
    missing
    return [nested $state]
}
last 1
"""
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        unchanged = next(c for c in server.documents[uri].facts.command_calls if c.name == 'puts')
        for version, replacement in enumerate(('a_longer_name', '\nputs moved\n', 'x'), start=2):
            edited = text.replace('puts original', replacement)
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
            first = next(c for c in server.documents[uri].facts.command_calls if c.name == 'puts')
            assert first is unchanged
    finally:
        server.shutdown()


def test_annotation_edits_refresh_cached_parameter_and_variable_types(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """# @alias State "enabled"|"disabled"
# @param state State
proc use {state} {
    set copy $state
    if {$copy eq "enabled"} {puts $copy} else {puts $copy}
    # @type State
    set configured [read stdin]
    puts $configured
}
"""
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        variants = (
            '\n' + text,
            text.replace('"disabled"', '"candidate"'),
            text.replace('@param state State', '@param state integer'),
            text.replace('@type State', '@type string[]'),
        )
        for version, edited in enumerate(variants, start=2):
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
        refs = server.documents[uri].facts.variable_references
        assert refs[-1].type_info is not None
        assert refs[-1].type_info.expression.text == 'string[]'
        assert refs[-1].exact_values == ()
    finally:
        server.shutdown()


def test_cached_value_checks_keep_locations_and_refresh_constraints(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = (
        'proc first {} {puts unchanged}\n'
        '# @param count integer|"auto"\n'
        'proc use {count} {\n'
        '    expr {$count + 1}\n'
        '    if {"invalid"} {puts yes}\n'
        '}\n'
    )
    server = new_server()
    try:
        diagnostics = server.open_document(uri, text, 1)
        assert [(d.code, d.severity) for d in diagnostics] == [
            ('invalid-expr-operand', 'warning'),
            ('invalid-expr-operand', 'error'),
        ]
        variants = (
            '\n\n' + text,
            text.replace('integer|"auto"', 'integer'),
            text.replace('"invalid"', '"yes"'),
        )
        for version, edited in enumerate(variants, start=2):
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
            for diagnostic in server.documents[uri].analysis.diagnostics:
                span = diagnostic.span
                source = edited[span.start.offset : span.end.offset]
                assert source in {'{$count + 1}', '"invalid"'}
    finally:
        server.shutdown()


@pytest.mark.parametrize('declaration', ['proc', 'define'])
def test_body_reuse_updates_parameter_and_procedure_scopes(
    tmp_path: Path, declaration: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {\n'
        '  meta command define {name params body} {\n'
        '    procedure {name {select 1}; params {select 2}; body {select 3}}\n'
        '  }\n'
        '}\n'
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    text = f'{declaration} old {{value}} {{set local $value; return $local}}\nold 1\n'
    server = new_server()
    try:
        assert server.open_document(uri, text, 1) == ()
        edited = text.replace('old', 'longer').replace('{value}', '{other}')
        server.change_document(uri, edited, 2)
        assert_fresh_analysis(server, uri, edited)
        assert [d.message for d in server.documents[uri].analysis.diagnostics] == [
            'Unresolved variable `value`.'
        ]
    finally:
        server.shutdown()


def test_cached_wrappers_refresh_shared_parameters_and_their_locations(tmp_path: Path) -> None:
    write_header_plugin(tmp_path)
    uri = (tmp_path / 'main.tcl').as_uri()
    text = (
        'proc factory {} {\n'
        '    set common {{-props -default .*}}\n'
        '    declare prove {-args {$common}} {puts $props}\n'
        '}\n'
    )
    server = new_server()
    try:
        assert server.open_document(uri, text, 1) == ()
        variants = ('\n' + text, text.replace('{-props', '{-engines'), text)
        for version, edited in enumerate(variants, start=2):
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
            procedure = next(p for p in server.documents[uri].facts.procedures if p.name == 'prove')
            (parameter,) = procedure.parameters
            assert edited[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
            expected = ['Unresolved variable `props`.'] if '-engines' in edited else []
            assert [d.message for d in server.documents[uri].analysis.diagnostics] == expected
    finally:
        server.shutdown()


def test_cached_wrappers_refresh_when_their_plugin_changes(tmp_path: Path) -> None:
    plugin = write_header_plugin(tmp_path)
    original = plugin.read_text()
    uri = (tmp_path / 'main.tcl').as_uri()
    text = 'set common {{-props}}\ndeclare prove {-args {$common}} {puts $props}\n'
    server = new_server()
    try:
        assert server.open_document(uri, text, 1) == ()

        plugin.write_text(
            original.replace(
                'parameters [expand [arguments $header]]', 'parameters [arguments $header]'
            )
        )
        diagnostics = server.change_document(uri, text, 2)

        assert [d.message for d in diagnostics] == ['Unresolved variable `props`.']
        assert_fresh_analysis(server, uri, text)
    finally:
        server.shutdown()


def test_cached_proc_parameters_follow_changes_to_known_variable_values(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = (
        'proc factory {} {\n'
        '    set common {props}\n'
        '    set alias $common\n'
        '    proc prove $alias {puts $props}\n'
        '}\n'
    )
    server = new_server()
    try:
        assert server.open_document(uri, text, 1) == ()
        variants = ('\n' + text, text.replace('{props}', '{engines}'), text)
        for version, edited in enumerate(variants, start=2):
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
            procedure = next(p for p in server.documents[uri].facts.procedures if p.name == 'prove')
            (parameter,) = procedure.parameters
            assert edited[parameter.span.start.offset : parameter.span.end.offset] == parameter.name
            expected = ['Unresolved variable `props`.'] if '{engines}' in edited else []
            assert [d.message for d in server.documents[uri].analysis.diagnostics] == expected
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    'prefix',
    [
        'namespace import ::custom::*\n',
        'package require Custom\n',
        '# tcl-ls: module Custom\n',
    ],
)
def test_body_reuse_tracks_imports_and_module_selection(tmp_path: Path, prefix: str) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command custom::body {script} {enter tcl body 1}}\n'
        'meta module Custom {meta command body {script} {enter tcl body 1}}\n'
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    body = 'proc example {} {body {set local 1; missing $local}}\n'
    server = new_server()
    try:
        server.open_document(uri, body, 1)
        for version, text in enumerate((prefix + body, body), start=2):
            server.change_document(uri, text, version)
            assert_fresh_analysis(server, uri, text)
            assert [d.message for d in server.documents[uri].analysis.diagnostics] == [
                'Unresolved command `missing`.'
                if text.startswith(prefix)
                else 'Unresolved command `body`.'
            ]
    finally:
        server.shutdown()


def test_cached_body_preserves_imports_and_dependencies(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Custom {meta command custom::body {script} {enter tcl body 1}}\n'
    )
    (tmp_path / 'support.tcl').write_text('package require Custom\n')
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """proc setup {} {
    source [file join [file dirname [info script]] support.tcl]
    namespace import ::custom::*
}
proc example {} {body {missing}}
"""
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        edited = '# move the procedures\n' + text
        server.change_document(uri, edited, 2)
        assert_fresh_analysis(server, uri, edited)
        assert [d.message for d in server.documents[uri].analysis.diagnostics] == [
            'Unresolved command `missing`.'
        ]
        # Keep both bodies unchanged while removing a transitive requirement.
        (tmp_path / 'support.tcl').write_text('puts removed\n')
        server.change_document(uri, edited, 3)
        assert_fresh_analysis(server, uri, edited)
        assert [d.message for d in server.documents[uri].analysis.diagnostics] == [
            'Unresolved command `body`.'
        ]
    finally:
        server.shutdown()


def test_body_plugins_receive_current_scope_after_an_edit(tmp_path: Path) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {meta command dynamic {} {plugin plugin.tcl emit}}\n'
    )
    (tmp_path / 'plugin.tcl').write_text(
        'proc emit {words info} {\n'
        '  set name p[lindex [split [dict get $info procedure-symbol-id] :] end]\n'
        '  return [list [list procedure "name {literal $name}; params {literal {}}"]]\n'
        '}\n'
    )
    uri = (tmp_path / 'main.tcl').as_uri()
    text = 'proc example {} {dynamic; p5}\n'
    server = new_server()
    try:
        assert server.open_document(uri, text, 1) == ()
        edited = '# move the body\n' + text
        diagnostics = server.change_document(uri, edited, 2)
        assert [d.message for d in diagnostics] == ['Unresolved command `p5`.']
        assert_fresh_analysis(server, uri, edited)
    finally:
        server.shutdown()


def test_highlighting_reuses_moved_blocks_with_nested_and_repeated_text(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """proc sample {value} {
    set data {{quoted "text"} {nested {data}}}
    switch -- $value {
        a {puts "text"; # first branch
           return [expr {1 + 2}]}
        b {puts "text"; # repeated text at a different position
           return [expr {1 + 2}]}
    }
    catch {puts "text"} result
    return $result
}
"""
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        assert_fresh_analysis(server, uri, text)
        for version, prefix in enumerate(('puts "λ"; ', '# extra line\n', ''), start=2):
            edited = prefix + text
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
    finally:
        server.shutdown()


def test_return_type_edits_refresh_cached_caller_bodies(tmp_path: Path) -> None:
    uri = (tmp_path / 'main.tcl').as_uri()
    text = """# @return [integer, string]
proc read_state {} {return {1 text}}
proc use {} {
    set pair [read_state]
    lassign $pair count state
    puts $count
    puts $state
}
"""
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        edits = (
            '# move all bodies\n' + text,
            text.replace('[integer, string]', '[string, integer]'),
            text.replace('# @return [integer, string]\n', ''),
            text,
        )
        for version, edited in enumerate(edits, start=2):
            server.change_document(uri, edited, version)
            assert_fresh_analysis(server, uri, edited)
            count = next(
                ref
                for ref in server.documents[uri].facts.variable_references
                if ref.name == 'count'
            )
            expected = 'string' if version == 3 else None if version == 4 else 'integer'
            assert (count.type_info.expression.text if count.type_info else None) == expected
    finally:
        server.shutdown()


def test_sourced_return_alias_edits_refresh_callers(tmp_path: Path) -> None:
    provider = tmp_path / 'provider.tcl'
    definitions = '# @alias State "enabled"|"disabled"\n# @return State\nproc read_state {} {return enabled}\n'
    provider.write_text(definitions)
    uri = (tmp_path / 'main.tcl').as_uri()
    text = 'source [file join [file dirname [info script]] provider.tcl]\nproc use {} {set state [read_state]; puts $state}\n'
    server = new_server()
    try:
        server.open_document(uri, text, 1)
        server.open_document(provider.as_uri(), definitions, 1)
        edits = (
            definitions.replace('"enabled"|"disabled"', 'integer'),
            definitions.replace('# @return State\n', ''),
            definitions,
        )
        for version, edited in enumerate(edits, start=2):
            provider.write_text(edited)
            server.change_document(provider.as_uri(), edited, version)
            assert_fresh_analysis(server, uri, text)
            reference = server.documents[uri].facts.variable_references[0]
            assert (reference.type_info is None) == (version == 3)
            assert reference.exact_values == (('enabled', 'disabled') if version == 4 else ())
    finally:
        server.shutdown()
