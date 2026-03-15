from __future__ import annotations

from dataclasses import dataclass

from tcl_lsp.analysis import AnalysisResult, DocumentFacts, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.parser import Parser


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    facts: DocumentFacts
    analysis: AnalysisResult


def _analyze(parser: Parser, uri: str, text: str) -> AnalysisSnapshot:
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(uri, text)
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)
    return AnalysisSnapshot(facts=facts, analysis=analysis)


def test_analysis_resolves_proc_calls_and_parameters(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///main.tcl',
        'proc greet {name} {puts $name}\ngreet World\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

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


def test_analysis_reports_duplicate_procs_and_unresolved_symbols(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///broken.tcl',
        'proc greet {} {puts $name}\nmissing_command\nproc greet {} {return ok}\n',
    )
    analysis = snapshot.analysis

    diagnostic_codes = [diagnostic.code for diagnostic in analysis.diagnostics]
    assert diagnostic_codes.count('duplicate-proc') == 2
    assert 'unresolved-command' in diagnostic_codes
    assert 'unresolved-variable' in diagnostic_codes


def test_analysis_tracks_namespace_resolution(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///namespace.tcl',
        'namespace eval app { proc greet {} {return ok} }\napp::greet\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert [scope.qualified_name for scope in facts.namespaces] == ['::app']
    assert [proc.qualified_name for proc in facts.procedures] == ['::app::greet']

    resolved_commands = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'app::greet'
    ]
    assert len(resolved_commands) == 1
    assert resolved_commands[0].uncertainty.state == 'resolved'


def test_analysis_includes_proc_comment_blocks_in_hovers(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///doc.tcl',
        '# Greets a user by name.\n'
        '# Returns nothing.\n'
        'proc greet {name} {puts $name}\n'
        'greet World\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

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


def test_analysis_uses_builtin_command_metadata_for_hovers(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///builtin.tcl', 'pwd\n')
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert analysis.diagnostics == ()

    command_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    )
    assert command_resolution.reference.name == 'pwd'
    assert command_resolution.uncertainty.state == 'resolved'
    assert len(command_resolution.target_symbol_ids) == 1

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    hover = hover_by_offset[facts.command_calls[0].name_span.start.offset]
    assert hover.startswith(
        'builtin command pwd\n\nReturn the absolute path of the current working directory.'
    )
    assert 'Returns the absolute path name of the current working directory.' in hover


def test_analysis_includes_single_builtin_signature_when_arguments_exist(
    parser: Parser,
) -> None:
    snapshot = _analyze(parser, 'file:///builtin_set.tcl', 'set value 1\n')
    facts = snapshot.facts
    analysis = snapshot.analysis

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    hover = hover_by_offset[facts.command_calls[0].name_span.start.offset]
    assert hover.startswith('builtin command set {varName args}\n\nRead and write variables.')
    assert 'With one argument, return the current value of varName.' in hover

    command_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    )
    assert command_resolution.uncertainty.state == 'resolved'
    assert len(command_resolution.target_symbol_ids) == 1


def test_analysis_groups_builtin_overloads_in_hover_output(parser: Parser) -> None:
    snapshot = _analyze(parser, 'file:///builtin_overload.tcl', 'after 100\n')
    facts = snapshot.facts
    analysis = snapshot.analysis

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    hover = hover_by_offset[facts.command_calls[0].name_span.start.offset]

    assert hover.startswith('builtin command after\n\n')
    assert '`after {ms}`\nExecute a command after a time delay' in hover
    assert '`after {idle script args}`\nSchedule a script to run when the event loop is idle' in hover
    assert (
        '`after {cancel idOrScript}`\nCancel a previously scheduled after handler' in hover
    )

    command_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    )
    builtin = builtin_command('after')
    assert builtin is not None
    assert command_resolution.uncertainty.state == 'resolved'
    assert len(command_resolution.target_symbol_ids) == len(builtin.overloads)


def test_analysis_supports_builtin_subcommand_hovers(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///builtin_namespace_subcommands.tcl',
        'namespace current\n'
        'namespace eval app {}\n'
        'namespace code {puts hi}\n'
        'namespace ensemble create\n'
        'dict get {a 1} a\n'
        'trace add command foo delete cb\n'
        'binary encode base64 data\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    target_names = {
        'namespace current',
        'namespace eval',
        'namespace code',
        'namespace ensemble create',
        'dict get',
        'trace add command',
        'binary encode base64',
    }
    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name in target_names
    }
    assert resolution_by_name == {name: 'resolved' for name in target_names}

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    subcommands = {
        command.name: command
        for command in facts.command_calls
        if command.name in target_names
    }
    assert subcommands.keys() == target_names

    for name in target_names:
        builtin = builtin_command(name)
        assert builtin is not None
        assert len(builtin.overloads) == 1
        overload = builtin.overloads[0]
        heading = overload.signature.removesuffix(' {}')
        assert hover_by_offset[subcommands[name].name_span.start.offset] == (
            f'builtin command {heading}\n\n{overload.documentation}'
        )


def test_analysis_tracks_catch_bodies_and_result_variables(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///catch.tcl',
        'proc helper {} {return ok}\n'
        'proc run {} {\n'
        '    catch {\n'
        '        set local [helper]\n'
        '    } message options\n'
        '    puts $message\n'
        '    puts $options\n'
        '    puts $local\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    bindings_by_name = {
        binding.name: binding.kind
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id
    }
    assert bindings_by_name['message'] == 'catch'
    assert bindings_by_name['options'] == 'catch'
    assert bindings_by_name['local'] == 'set'

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    variable_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolutions['message'] == 'resolved'
    assert variable_resolutions['options'] == 'resolved'
    assert variable_resolutions['local'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_references_inside_braced_if_conditions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///if_condition.tcl',
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {$flag && [helper]} {\n'
        '        return ok\n'
        '    } elseif {[helper]} then {\n'
        '        return alt\n'
        '    }\n'
        '}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    flag_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'flag'
    ]
    assert len(flag_references) == 1
    assert flag_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_tracks_static_if_bodies_for_metadata_guards() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///meta_file.tcl',
        'if {[llength [info commands meta]] == 0} {\n'
        '    proc meta {args} {}\n'
        '}\n'
        '# Builtin metadata entry.\n'
        'meta command after {ms}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    assert [proc.qualified_name for proc in facts.procedures] == ['::meta']
    assert analysis.diagnostics == ()


def test_analysis_treats_meta_command_as_builtin() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///meta_builtin.tcl',
        '# Builtin metadata entry.\nmeta command after {ms}\n',
    )
    facts = extractor.extract(parse_result)
    workspace.update(facts.uri, facts)
    analysis = resolver.analyze(facts.uri, facts, workspace)

    meta_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'meta'
    )
    assert meta_resolution.uncertainty.state == 'resolved'
    assert len(meta_resolution.target_symbol_ids) == 1

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    hover = hover_by_offset[facts.command_calls[0].name_span.start.offset]
    assert hover.startswith(
        'builtin command meta {kind name signature}\n\n'
        'Declare metadata for Tcl language entities.'
    )
    assert 'structured documentation instead of executable behavior' in hover.replace(
        '\n', ' '
    )
    assert analysis.diagnostics == ()
