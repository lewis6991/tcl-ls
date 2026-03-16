from __future__ import annotations

from tcl_lsp.analysis import FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.parser import Parser

from .support import analyze_document as _analyze


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


def test_analysis_global_links_proc_references_to_global_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///global.tcl',
        'set shared 0\n'
        'proc run {} {\n'
        '    global shared\n'
        '    incr shared\n'
        '    puts $shared\n'
        '}\n'
        'vwait shared\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    namespace_bindings = [
        binding
        for binding in facts.variable_bindings
        if binding.scope_id == 'namespace::::' and binding.name == 'shared'
    ]
    proc_bindings = [
        binding
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id and binding.name == 'shared'
    ]

    assert {binding.kind for binding in namespace_bindings} == {'set', 'global'}
    assert {binding.kind for binding in proc_bindings} == {'global', 'incr'}
    assert len({binding.symbol_id for binding in namespace_bindings}) == 1
    assert {binding.symbol_id for binding in proc_bindings} == {
        namespace_bindings[0].symbol_id,
    }

    shared_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'shared'
    ]
    assert len(shared_resolutions) == 4
    assert all(resolution.uncertainty.state == 'resolved' for resolution in shared_resolutions)
    assert analysis.diagnostics == ()


def test_analysis_variable_links_proc_references_to_namespace_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///variable.tcl',
        'namespace eval app {\n'
        '    variable counter 0\n'
        '    proc run {} {\n'
        '        variable counter\n'
        '        incr counter\n'
        '        puts $counter\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::app::run')
    namespace_bindings = [
        binding
        for binding in facts.variable_bindings
        if binding.scope_id == 'namespace::::app' and binding.name == 'counter'
    ]
    proc_bindings = [
        binding
        for binding in facts.variable_bindings
        if binding.scope_id == run_proc.symbol_id and binding.name == 'counter'
    ]

    assert {binding.kind for binding in namespace_bindings} == {'variable'}
    assert {binding.kind for binding in proc_bindings} == {'variable', 'incr'}
    assert len({binding.symbol_id for binding in namespace_bindings}) == 1
    assert {binding.symbol_id for binding in proc_bindings} == {
        namespace_bindings[0].symbol_id,
    }

    counter_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'counter'
    ]
    assert len(counter_resolutions) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in counter_resolutions)
    assert analysis.diagnostics == ()


def test_analysis_treats_upvar_aliases_as_local_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///upvar.tcl',
        'proc helper {name} {\n'
        '    upvar 1 $name state\n'
        '    puts $state\n'
        '}\n'
        'proc run {} {\n'
        '    set value ok\n'
        '    helper value\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    helper_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::helper')
    helper_bindings = [
        binding for binding in facts.variable_bindings if binding.scope_id == helper_proc.symbol_id
    ]
    assert {(binding.name, binding.kind) for binding in helper_bindings} >= {
        ('name', 'parameter'),
        ('state', 'upvar'),
    }

    state_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'state'
    ]
    assert len(state_resolutions) == 1
    assert state_resolutions[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_commands_via_namespace_import(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///namespace_import.tcl',
        'namespace eval helpers {\n'
        '    proc greet {} {return ok}\n'
        '}\n'
        'namespace eval app {\n'
        '    namespace import ::helpers::*\n'
        '    proc run {} {\n'
        '        greet\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert len(facts.command_imports) == 1
    assert facts.command_imports[0].kind == 'namespace-wildcard'
    assert facts.command_imports[0].namespace == '::app'
    assert facts.command_imports[0].target_name == '::helpers'

    greet_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'greet'
    )
    assert greet_resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_treats_dynamic_namespace_variable_links_as_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_variable_link.tcl',
        'namespace eval app {\n'
        '    proc run {ns} {\n'
        '        variable ${ns}::counter\n'
        '        puts $counter\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::app::run')
    run_bindings = [
        binding for binding in facts.variable_bindings if binding.scope_id == run_proc.symbol_id
    ]
    assert {(binding.name, binding.kind) for binding in run_bindings} >= {
        ('ns', 'parameter'),
        ('counter', 'variable'),
    }

    counter_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'counter'
    )
    assert counter_resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_variable_uses_inside_namespace_eval_blocks(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///namespace_eval_variable_uses.tcl',
        'namespace eval app {\n'
        '    variable counter\n'
        '    if {![info exists counter]} { set counter 0 }\n'
        '    variable options\n'
        '    array set options {proxy_host localhost}\n'
        '    array names options\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    namespace_bindings = [
        binding for binding in facts.variable_bindings if binding.scope_id == 'namespace::::app'
    ]
    assert {(binding.name, binding.kind) for binding in namespace_bindings} >= {
        ('counter', 'variable'),
        ('counter', 'set'),
        ('options', 'variable'),
        ('options', 'array'),
    }

    variable_resolutions = [
        resolution for resolution in analysis.resolutions if resolution.reference.kind == 'variable'
    ]
    unique_sites = {
        (resolution.reference.name, resolution.reference.span.start.offset)
        for resolution in variable_resolutions
    }
    assert len(unique_sites) == 4
    assert {name for name, _ in unique_sites} == {'counter', 'options'}
    assert all(resolution.uncertainty.state == 'resolved' for resolution in variable_resolutions)
    assert analysis.diagnostics == ()


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
        resolution for resolution in analysis.resolutions if resolution.reference.kind == 'command'
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
        resolution for resolution in analysis.resolutions if resolution.reference.kind == 'command'
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
    assert (
        '`after {idle script args}`\nSchedule a script to run when the event loop is idle' in hover
    )
    assert '`after {cancel idOrScript}`\nCancel a previously scheduled after handler' in hover

    command_resolution = next(
        resolution for resolution in analysis.resolutions if resolution.reference.kind == 'command'
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
        if resolution.reference.kind == 'command' and resolution.reference.name in target_names
    }
    assert resolution_by_name == dict.fromkeys(target_names, 'resolved')

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    subcommands = {
        command.name: command for command in facts.command_calls if command.name in target_names
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


def test_analysis_resolves_required_tk_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tk.tcl',
        'package require Tk\nframe .f\npack .f\nwm title . "Demo"\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['frame'] == 'resolved'
    assert resolution_by_name['pack'] == 'resolved'
    assert resolution_by_name['wm'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_required_msgcat_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///msgcat.tcl',
        'package require msgcat\n'
        'namespace import ::msgcat::*\n'
        'mcset en greeting Hello\n'
        '::msgcat::mc greeting\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['mcset'] == 'resolved'
    assert resolution_by_name['::msgcat::mc'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_required_tcloo_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcloo.tcl',
        'package require TclOO\n'
        'oo::class create Foo {}\n'
        'oo::define Foo {}\n'
        'oo::objdefine ::oo::object {}\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['oo::class'] == 'resolved'
    assert resolution_by_name['oo::define'] == 'resolved'
    assert resolution_by_name['oo::objdefine'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_common_tcllib_builtin_metadata(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcllib_builtin_metadata.tcl',
        'package require clay\n'
        'package require fileutil\n'
        'package require cmdline\n'
        'package require log\n'
        'package require doctools::text\n'
        'package require oo::meta\n'
        'clay::define ::demo {}\n'
        'fileutil::cat ./README\n'
        'fileutil::findByPattern . -glob *.tcl\n'
        'fileutil::writeFile ./out.txt contents\n'
        'fileutil::tempfile tmp\n'
        'fileutil::stripN /tmp/work/file.tcl 2\n'
        'cmdline::getArgv0\n'
        'log::log info hello\n'
        'log::debug trace\n'
        'text::begin\n'
        'text::+ hello\n'
        'text::newline\n'
        'text::indented 2 {text::+ world}\n'
        'text::done\n'
        '::oo::meta::info ::demo getnull method_ensemble\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name
        in {
            'clay::define',
            'fileutil::cat',
            'fileutil::findByPattern',
            'fileutil::writeFile',
            'fileutil::tempfile',
            'fileutil::stripN',
            'cmdline::getArgv0',
            'log::log',
            'log::debug',
            'text::begin',
            'text::+',
            'text::newline',
            'text::indented',
            'text::done',
            '::oo::meta::info',
        }
    }
    assert resolution_by_name == {
        'clay::define': 'resolved',
        'fileutil::cat': 'resolved',
        'fileutil::findByPattern': 'resolved',
        'fileutil::writeFile': 'resolved',
        'fileutil::tempfile': 'resolved',
        'fileutil::stripN': 'resolved',
        'cmdline::getArgv0': 'resolved',
        'log::log': 'resolved',
        'log::debug': 'resolved',
        'text::begin': 'resolved',
        'text::+': 'resolved',
        'text::newline': 'resolved',
        'text::indented': 'resolved',
        'text::done': 'resolved',
        '::oo::meta::info': 'resolved',
    }
    assert analysis.diagnostics == ()


def test_analysis_treats_tcl_oo_alias_as_builtin_package(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcl_oo_alias.tcl',
        'package require tcl::oo\noo::class create Foo {}\n',
    )
    analysis = snapshot.analysis

    resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'oo::class'
    )
    assert resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_tcltest_commands_in_test_files_without_explicit_import(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///suite.test',
        'test sample {} -body {return ok}\n',
    )
    analysis = snapshot.analysis

    resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'test'
    )
    assert resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_tcltest_commands_in_test_tcl_files_without_explicit_import(
    parser: Parser,
) -> None:
    snapshot = _analyze(
        parser,
        'file:///suite.test.tcl',
        'test sample {} -body {return ok}\n',
    )
    analysis = snapshot.analysis

    resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'test'
    )
    assert resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_additional_required_tk_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tk_more.tcl',
        'package require Tk\n'
        'bind . <Escape> {destroy .}\n'
        'font families\n'
        'tkwait visibility .\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['bind'] == 'resolved'
    assert resolution_by_name['font'] == 'resolved'
    assert resolution_by_name['tkwait'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_imported_tcltest_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcltest_import.tcl',
        'package require tcltest\n'
        'namespace import ::tcltest::*\n'
        'loadTestedCommands\n'
        'test sample {} -body {return ok}\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['loadTestedCommands'] == 'resolved'
    assert resolution_by_name['test'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_qualified_tcltest_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcltest_qualified.tcl',
        'package require tcltest\n::tcltest::configure -verbose p\n::tcltest::loadTestedCommands\n',
    )
    analysis = snapshot.analysis

    configure_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name == '::tcltest::configure'
    )
    load_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name == '::tcltest::loadTestedCommands'
    )
    assert configure_resolution.uncertainty.state == 'resolved'
    assert load_resolution.uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


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


def test_analysis_tracks_additional_builtin_variable_writers_and_outputs(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///writers.tcl',
        'proc run {} {\n'
        '    append message hello world\n'
        '    lappend items a b\n'
        '    gets stdin line\n'
        '    lassign $items first second\n'
        '    scan "1 2" "%d %d" left right\n'
        '    binary scan "AB" H* hex\n'
        '    puts $message\n'
        '    puts $line\n'
        '    puts $first\n'
        '    puts $second\n'
        '    puts $left\n'
        '    puts $right\n'
        '    puts $hex\n'
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
    assert bindings_by_name['message'] == 'append'
    assert bindings_by_name['items'] == 'lappend'
    assert bindings_by_name['line'] == 'gets'
    assert bindings_by_name['first'] == 'lassign'
    assert bindings_by_name['second'] == 'lassign'
    assert bindings_by_name['left'] == 'scan'
    assert bindings_by_name['right'] == 'scan'
    assert bindings_by_name['hex'] == 'scan'

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert {name for name, _ in variable_resolutions} == {
        'items',
        'message',
        'line',
        'first',
        'second',
        'left',
        'right',
        'hex',
    }
    assert set(variable_resolutions.values()) == {'resolved'}
    assert analysis.diagnostics == ()


def test_analysis_tracks_regexp_and_regsub_output_variables(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///regexp_outputs.tcl',
        'proc run {text} {\n'
        '    regexp -start 1 -indices {(..)(..)} $text match left right\n'
        '    regsub -all -start 1 {foo} $text bar replaced\n'
        '    puts $match\n'
        '    puts $left\n'
        '    puts $right\n'
        '    puts $replaced\n'
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
    assert bindings_by_name['match'] == 'regexp'
    assert bindings_by_name['left'] == 'regexp'
    assert bindings_by_name['right'] == 'regexp'
    assert bindings_by_name['replaced'] == 'regsub'

    variable_resolutions = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolutions['text'] == 'resolved'
    assert variable_resolutions['match'] == 'resolved'
    assert variable_resolutions['left'] == 'resolved'
    assert variable_resolutions['right'] == 'resolved'
    assert variable_resolutions['replaced'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_normalizes_punctuated_and_array_variable_names(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///variables.tcl',
        'proc run {pname} {\n'
        '    global ftp\n'
        '    set ftp(conn) ok\n'
        '    puts "$pname:"\n'
        '    puts ${ftp(conn)}\n'
        '}\n',
    )
    analysis = snapshot.analysis

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_states['pname'] == 'resolved'
    assert variable_states['ftp'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_dynamic_array_element_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_array_bindings.tcl',
        'proc run {n} {\n'
        '    set p($n) ok\n'
        '    puts $p($n)\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    run_bindings = [
        binding for binding in facts.variable_bindings if binding.scope_id == run_proc.symbol_id
    ]
    assert {(binding.name, binding.kind) for binding in run_bindings} >= {
        ('n', 'parameter'),
        ('p', 'set'),
    }

    variable_resolutions = [
        resolution for resolution in analysis.resolutions if resolution.reference.kind == 'variable'
    ]
    assert {resolution.reference.name for resolution in variable_resolutions} == {'n', 'p'}
    assert all(resolution.uncertainty.state == 'resolved' for resolution in variable_resolutions)
    assert analysis.diagnostics == ()


def test_analysis_does_not_normalize_dynamic_scalar_suffix_names(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///dynamic_scalar_suffix.tcl',
        'proc run {n} {\n'
        '    set p($n)suffix ok\n'
        '    puts $p\n'
        '}\n',
    )
    analysis = snapshot.analysis

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_states['n'] == 'resolved'
    assert variable_states['p'] == 'unresolved'

    diagnostics = [
        diagnostic.code for diagnostic in analysis.diagnostics if diagnostic.code == 'unresolved-variable'
    ]
    assert diagnostics == ['unresolved-variable']


def test_analysis_tracks_switch_branch_bodies_from_list_form(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_list.tcl',
        'proc helper {} {return ok}\n'
        'proc run {kind} {\n'
        '    switch -- $kind {\n'
        '        alpha {\n'
        '            set local [helper]\n'
        '            puts $local\n'
        '        }\n'
        '        beta -\n'
        '        default {\n'
        '            return done\n'
        '        }\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    local_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'local'
    ]
    assert len(local_references) == 1
    assert local_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_tracks_switch_branch_bodies_from_argument_form(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_args.tcl',
        'proc helper {} {return ok}\n'
        'proc run {kind} {\n'
        '    switch -- $kind \\\n'
        '        alpha {\n'
        '            helper\n'
        '        } \\\n'
        '        default {\n'
        '            puts $kind\n'
        '        }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    kind_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'kind'
    ]
    assert len({resolution.reference.span.start.offset for resolution in kind_references}) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in kind_references)
    assert analysis.diagnostics == ()


def test_analysis_tracks_regexp_switch_match_variables(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///switch_regexp.tcl',
        'proc run {value} {\n'
        '    switch -regexp -matchvar matches -indexvar indices -- $value {\n'
        '        {^a(b+)$} {\n'
        '            puts [lindex $matches 1]\n'
        '            puts [lindex $indices 0]\n'
        '        }\n'
        '        default {\n'
        '            puts $matches\n'
        '            puts $indices\n'
        '        }\n'
        '    }\n'
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
    assert bindings_by_name['matches'] == 'switch'
    assert bindings_by_name['indices'] == 'switch'

    match_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'matches', 'indices'}
    ]
    unique_match_sites = {
        (resolution.reference.name, resolution.reference.span.start.offset)
        for resolution in match_resolutions
    }
    assert len(unique_match_sites) == 4
    assert {name for name, _ in unique_match_sites} == {'matches', 'indices'}
    assert all(resolution.uncertainty.state == 'resolved' for resolution in match_resolutions)
    assert analysis.diagnostics == ()


def test_analysis_tracks_for_while_and_lmap_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///loop_bodies.tcl',
        'proc helper {} {return ok}\n'
        'proc run {items flag} {\n'
        '    for {set i 0} {$i < 2} {incr i} {\n'
        '        helper\n'
        '        puts $i\n'
        '    }\n'
        '    while {$flag} {\n'
        '        set flag 0\n'
        '        helper\n'
        '    }\n'
        '    lmap item $items {\n'
        '        helper\n'
        '        puts $item\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 3
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'flag', 'i', 'item', 'items'}
    }
    assert {name for name, _ in variable_resolutions} == {'flag', 'i', 'item', 'items'}
    assert set(variable_resolutions.values()) == {'resolved'}
    assert analysis.diagnostics == ()


def test_analysis_tracks_multi_source_foreach_and_lmap_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///multi_loop_pairs.tcl',
        'proc helper {} {return ok}\n'
        'proc run {left right} {\n'
        '    foreach item $left weight $right {\n'
        '        helper\n'
        '        puts $item\n'
        '        puts $weight\n'
        '    }\n'
        '    lmap value $left code $right {\n'
        '        helper\n'
        '        list $value $code\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    helper_calls = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'helper'
    ]
    assert len(helper_calls) == 2
    assert all(resolution.uncertainty.state == 'resolved' for resolution in helper_calls)

    variable_resolutions = {
        (
            resolution.reference.name,
            resolution.reference.span.start.offset,
        ): resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'item', 'weight', 'value', 'code', 'left', 'right'}
    }
    assert {name for name, _ in variable_resolutions} == {
        'item',
        'weight',
        'value',
        'code',
        'left',
        'right',
    }
    assert set(variable_resolutions.values()) == {'resolved'}
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


def test_analysis_tracks_nested_if_conditions_inside_command_substitutions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()

    parse_result = parser.parse_document(
        'file:///nested_if_condition.tcl',
        'proc helper {} {return 1}\n'
        'proc run {flag} {\n'
        '    if {[if {$flag} {helper}]} {\n'
        '        return ok\n'
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
    assert len(helper_calls) == 1
    assert helper_calls[0].uncertainty.state == 'resolved'

    flag_references = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'flag'
    ]
    assert len(flag_references) == 1
    assert flag_references[0].uncertainty.state == 'resolved'
    assert analysis.diagnostics == ()


def test_extractor_does_not_duplicate_variable_references_in_command_substitutions() -> None:
    parser = Parser()
    extractor = FactExtractor(parser)

    parse_result = parser.parse_document(
        'file:///command_substitution_refs.tcl',
        'puts [foo $x [bar $y]]\n',
    )
    facts = extractor.extract(parse_result)

    assert [
        (reference.name, reference.span.start.offset, reference.span.end.offset)
        for reference in facts.variable_references
    ] == [
        ('x', 10, 12),
        ('y', 18, 20),
    ]


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
        'builtin command meta {kind name signature}\n\nDeclare metadata for Tcl language entities.'
    )
    assert 'structured documentation instead of executable behavior' in hover.replace('\n', ' ')
    assert analysis.diagnostics == ()
