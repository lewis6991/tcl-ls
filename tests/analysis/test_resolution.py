from __future__ import annotations

from tcl_lsp.analysis import DocumentFacts, FactExtractor, Resolver, WorkspaceIndex
from tcl_lsp.analysis.builtins import builtin_command
from tcl_lsp.metadata_paths import DEFAULT_METADATA_REGISTRY
from tcl_lsp.parser import Parser

from .support import analyze_document as _analyze
from .support import analyze_workspace as _analyze_workspace


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


def test_analysis_reports_no_diagnostics_for_metadata_files(parser: Parser) -> None:
    extractor = FactExtractor(parser)
    resolver = Resolver()
    workspace = WorkspaceIndex()
    facts_by_uri: dict[str, DocumentFacts] = {}

    metadata_paths = sorted(DEFAULT_METADATA_REGISTRY.metadata_files())
    assert metadata_paths

    for metadata_path in metadata_paths:
        text = metadata_path.read_text(encoding='utf-8')
        parse_result = parser.parse_document(metadata_path.as_uri(), text)
        facts = extractor.extract(parse_result)
        workspace.update(facts.uri, facts)
        facts_by_uri[facts.uri] = facts

    diagnostics_by_uri = {}
    for uri, facts in facts_by_uri.items():
        diagnostics = resolver.analyze(uri, facts, workspace).diagnostics
        if diagnostics:
            diagnostics_by_uri[uri] = tuple(diagnostic.code for diagnostic in diagnostics)

    assert diagnostics_by_uri == {}


def test_analysis_resolves_tcllib_metadata_from_umbrella_packages(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcllib_umbrella_packages.tcl',
        'package require json\n'
        'package require struct\n'
        'proc run {} {\n'
        '    struct::set include seen alpha\n'
        '    puts $seen\n'
        '}\n'
        'json::json2dict {}\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name in {'json::json2dict', 'struct::set include'}
    }
    assert resolution_by_name == {
        'json::json2dict': 'resolved',
        'struct::set include': 'resolved',
    }

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'seen'
    }
    assert variable_states == {'seen': 'resolved'}
    assert analysis.diagnostics == ()


def test_fact_extractor_skips_lexical_spans_when_parse_result_is_omitted(parser: Parser) -> None:
    extractor = FactExtractor(parser)
    parse_result = parser.parse_document(
        'file:///semantic.tcl',
        '# doc\nproc greet {name} {\n    # body\n    puts "hello [list ${name}]"\n}\n',
    )

    facts_with_spans = extractor.extract(parse_result)
    facts_without_spans = extractor.extract(parse_result, include_parse_result=False)

    assert facts_with_spans.comment_spans
    assert facts_with_spans.string_spans
    assert facts_with_spans.operator_spans

    assert facts_without_spans.parse_result is None
    assert facts_without_spans.comment_spans == ()
    assert facts_without_spans.string_spans == ()
    assert facts_without_spans.operator_spans == ()
    assert [procedure.qualified_name for procedure in facts_without_spans.procedures] == ['::greet']


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


def test_analysis_tracks_try_handlers_and_finally(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///try.tcl',
        'proc run {} {\n'
        '    try {\n'
        '        set status ok\n'
        '    } trap {POSIX EACCES} {message options} {\n'
        '        puts $message\n'
        '        dict get $options -errorcode\n'
        '    } on ok {value} {\n'
        '        puts $value\n'
        '    } finally {\n'
        '        puts $status\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    run_proc = next(proc for proc in facts.procedures if proc.qualified_name == '::run')
    run_bindings = [
        binding for binding in facts.variable_bindings if binding.scope_id == run_proc.symbol_id
    ]
    assert {(binding.name, binding.kind) for binding in run_bindings} >= {
        ('status', 'set'),
        ('message', 'catch'),
        ('options', 'catch'),
        ('value', 'catch'),
    }

    try_resolutions = [
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
        and resolution.reference.name in {'message', 'options', 'status', 'value'}
    ]
    assert {resolution.reference.name for resolution in try_resolutions} == {
        'message',
        'options',
        'status',
        'value',
    }
    assert all(resolution.uncertainty.state == 'resolved' for resolution in try_resolutions)
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


def test_analysis_resolves_builtin_package_metadata_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///cmdline_bindings.tcl',
        'package require cmdline\n'
        'proc run {args} {\n'
        '    while {[cmdline::getopt args {verbose output.arg} opt arg]} {\n'
        '        puts $opt\n'
        '        puts $arg\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_states['opt'] == 'resolved'
    assert variable_states['arg'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_workspace_package_helper_metadata_bindings(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tmp/fileutil.tcl',
        'namespace eval fileutil {\n'
        '    proc Spec {check alist ov fv args} {}\n'
        '    proc run {args} {\n'
        '        Spec Writable $args opts fname data\n'
        '        puts $opts\n'
        '        puts $fname\n'
        '        puts $data\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_states['opts'] == 'resolved'
    assert variable_states['fname'] == 'resolved'
    assert variable_states['data'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_imported_package_helper_metadata_bindings(parser: Parser) -> None:
    snapshot = _analyze_workspace(
        parser,
        documents=(
            (
                'file:///tmp/asn.tcl',
                'namespace eval asn {\n'
                '    proc asnGetApplication {data_var appNumber_var {content_var {}} {encodingType_var {}}} {}\n'
                '}\n',
            ),
            (
                'file:///tmp/ldap.tcl',
                'namespace eval ldap {\n'
                '    namespace import ::asn::*\n'
                '    proc run {response} {\n'
                '        asnGetApplication response appNum\n'
                '        puts $appNum\n'
                '    }\n'
                '}\n',
            ),
        ),
        target_uri='file:///tmp/ldap.tcl',
    )
    analysis = snapshot.analysis

    appnum_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable' and resolution.reference.name == 'appNum'
    )
    assert appnum_resolution.uncertainty.state == 'resolved'
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
    assert hover.startswith(
        'builtin command set {varName ? newValue ?}\n\nRead and write variables.'
    )
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
    meta_command_resolution = next(
        resolution
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command' and resolution.reference.name == 'meta command'
    )
    assert meta_resolution.uncertainty.state == 'resolved'
    assert len(meta_resolution.target_symbol_ids) == 1
    assert meta_command_resolution.uncertainty.state == 'resolved'
    assert len(meta_command_resolution.target_symbol_ids) == 3

    hover_by_offset = {hover.span.start.offset: hover.contents for hover in analysis.hovers}
    meta_command_call = next(
        command_call for command_call in facts.command_calls if command_call.name == 'meta command'
    )
    hover = hover_by_offset[meta_command_call.name_span.start.offset]
    assert hover.startswith('builtin command meta command\n\n`meta command {name shape}`')
    assert '`meta command {name shape body}`' in hover
    assert '`meta command {name variants body}`' in hover
    assert 'command or command prefix' in hover.replace('\n', ' ').lower()
    assert analysis.diagnostics == ()
