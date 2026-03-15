from __future__ import annotations

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.parser import Parser


def test_analysis_resolves_proc_calls_and_parameters() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///main.tcl',
        'proc greet {name} {puts $name}\ngreet World\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert [proc.qualified_name for proc in facts.procedures] == ['::greet']
    assert [binding.name for binding in facts.variable_bindings] == ['name']

    command_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert command_resolutions['greet'] == 'resolved'

    variable_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolutions['name'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_reports_duplicate_procs_and_unresolved_symbols() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///broken.tcl',
        'proc greet {} {puts $name}\nunknown\nproc greet {} {return ok}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    diagnostic_codes = [diagnostic.code for diagnostic in analysis.diagnostics]
    assert diagnostic_codes.count('duplicate-proc') == 2
    assert 'unresolved-command' in diagnostic_codes
    assert 'unresolved-variable' in diagnostic_codes


def test_analysis_tracks_namespace_resolution() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///namespace.tcl',
        'namespace eval app { proc greet {} {return ok} }\napp::greet\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert [scope.qualified_name for scope in facts.namespaces] == ['::app']
    assert [proc.qualified_name for proc in facts.procedures] == ['::app::greet']

    resolved_commands = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'app::greet'
    ]
    assert len(resolved_commands) == 1
    assert resolved_commands[0].uncertainty.state == 'resolved'


def test_analysis_includes_proc_comment_blocks_in_hovers() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///doc.tcl',
        '# Greets a user by name.\n'
        '# Returns nothing.\n'
        'proc greet {name} {puts $name}\n'
        'greet World\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert facts.procedures[0].documentation == 'Greets a user by name.\nReturns nothing.'

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    assert (
        hover_by_offset[facts.procedures[0].name_span.start.offset]
        == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'
    )

    greet_call = next(
        command
        for command in facts.command_calls
        if command.name == 'greet' and command.name_span.start.line == 3
    )
    assert (
        hover_by_offset[greet_call.name_span.start.offset]
        == 'proc ::greet(name)\n\nGreets a user by name.\nReturns nothing.'
    )
