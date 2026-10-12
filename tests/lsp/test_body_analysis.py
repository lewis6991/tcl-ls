from pathlib import Path

import pytest
from lsprotocol import types

from tcl_lsp.lsp import LanguageServer
from tests.lsp_support import process_message


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
        actual = server.documents[uri]
        expected = fresh.documents[uri]
        assert actual.facts == expected.facts
        assert actual.analysis == expected.analysis
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


@pytest.mark.parametrize('declaration', ['proc', 'define'])
def test_body_reuse_updates_parameter_and_procedure_scopes(
    tmp_path: Path, declaration: str
) -> None:
    (tmp_path / 'tcllsrc.tcl').write_text(
        'meta module Tcl {\n'
        '  meta command define {name params body} {\n'
        '    procedure {name select 1; params select 2; body select 3}\n'
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
        '  return [list [list procedure "name literal $name; params literal {}"]]\n'
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
