from __future__ import annotations

from tcl_lsp.parser import Parser

from .support import analyze_document as _analyze


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


def test_analysis_collects_tcloo_methods_from_definition_bodies(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcloo_body_methods.tcl',
        'package require TclOO\n'
        'oo::class create ::demo::Widget {\n'
        '    method greet {name} {\n'
        '        my variable seen\n'
        '        set seen $name\n'
        '        next $name\n'
        '        return [self]\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert '::demo::Widget method greet' in {
        procedure.qualified_name for procedure in facts.procedures
    }

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['method'] == 'resolved'
    assert resolution_by_name['my'] == 'resolved'
    assert resolution_by_name['next'] == 'resolved'
    assert resolution_by_name['self'] == 'resolved'

    variable_resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolution_by_name['name'] == 'resolved'
    assert variable_resolution_by_name['seen'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_collects_inline_tcloo_define_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcloo_inline_methods.tcl',
        'package require TclOO\n'
        'oo::class create Foo {}\n'
        'oo::define Foo method greet {name} {\n'
        '    my variable seen\n'
        '    set seen $name\n'
        '    return [self]\n'
        '}\n'
        'oo::define Foo constructor {value} {\n'
        '    set copy $value\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert {'::Foo method greet', '::Foo constructor'} <= {
        procedure.qualified_name for procedure in facts.procedures
    }

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['method'] == 'resolved'
    assert resolution_by_name['constructor'] == 'resolved'
    assert resolution_by_name['my'] == 'resolved'
    assert resolution_by_name['self'] == 'resolved'

    variable_resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolution_by_name['name'] == 'resolved'
    assert variable_resolution_by_name['seen'] == 'resolved'
    assert variable_resolution_by_name['value'] == 'resolved'
    assert 'copy' in {binding.name for binding in facts.variable_bindings}
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


def test_analysis_resolves_additional_tcllib_builtin_metadata(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tcllib_additional_builtin_metadata.tcl',
        'package require asn\n'
        'package require json::write\n'
        'package require logger\n'
        'package require struct::set\n'
        'package require textutil\n'
        'package require textutil::adjust\n'
        'package require textutil::repeat\n'
        'package require textutil::split\n'
        'package require textutil::string\n'
        'package require textutil::tabify\n'
        'package require textutil::trim\n'
        'package require textutil::wcswidth\n'
        'proc run {payload} {\n'
        '    asn::asnGetApplication payload appNum content encoding\n'
        '    struct::set include seen alpha\n'
        '    puts $appNum\n'
        '    puts $content\n'
        '    puts $encoding\n'
        '    puts $seen\n'
        '}\n'
        'json::write object name [json::write string Demo]\n'
        'json::write array 1 2 3\n'
        'logger::setlevel debug\n'
        'logger::import -force demo\n'
        'logger::servicecmd demo\n'
        'struct::set equal {a b} {b a}\n'
        'struct::set intersect3 {a b} {b c}\n'
        'textutil::cap hello\n'
        'textutil::adjust {one two three} -length 8\n'
        'textutil::strRepeat . 3\n'
        'textutil::splitx {a b}\n'
        'textutil::trim { hello }\n'
        'textutil::tabify {a   b}\n'
        'textutil::adjust::indent {x} {  }\n'
        'textutil::repeat::blank 2\n'
        'textutil::split::splitn hello 2\n'
        'textutil::string::uncap Demo\n'
        'textutil::tabify::untabify {a\tb}\n'
        'textutil::trim::trimleft { hello }\n'
        'textutil::wcswidth hello\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
        and resolution.reference.name
        in {
            'asn::asnGetApplication',
            'json::write object',
            'json::write string',
            'json::write array',
            'logger::setlevel',
            'logger::import',
            'logger::servicecmd',
            'struct::set include',
            'struct::set equal',
            'struct::set intersect3',
            'textutil::cap',
            'textutil::adjust',
            'textutil::strRepeat',
            'textutil::splitx',
            'textutil::trim',
            'textutil::tabify',
            'textutil::adjust::indent',
            'textutil::repeat::blank',
            'textutil::split::splitn',
            'textutil::string::uncap',
            'textutil::tabify::untabify',
            'textutil::trim::trimleft',
            'textutil::wcswidth',
        }
    }
    assert resolution_by_name == {
        'asn::asnGetApplication': 'resolved',
        'json::write object': 'resolved',
        'json::write string': 'resolved',
        'json::write array': 'resolved',
        'logger::setlevel': 'resolved',
        'logger::import': 'resolved',
        'logger::servicecmd': 'resolved',
        'struct::set include': 'resolved',
        'struct::set equal': 'resolved',
        'struct::set intersect3': 'resolved',
        'textutil::cap': 'resolved',
        'textutil::adjust': 'resolved',
        'textutil::strRepeat': 'resolved',
        'textutil::splitx': 'resolved',
        'textutil::trim': 'resolved',
        'textutil::tabify': 'resolved',
        'textutil::adjust::indent': 'resolved',
        'textutil::repeat::blank': 'resolved',
        'textutil::split::splitn': 'resolved',
        'textutil::string::uncap': 'resolved',
        'textutil::tabify::untabify': 'resolved',
        'textutil::trim::trimleft': 'resolved',
        'textutil::wcswidth': 'resolved',
    }

    variable_states = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_states['appNum'] == 'resolved'
    assert variable_states['content'] == 'resolved'
    assert variable_states['encoding'] == 'resolved'
    assert variable_states['seen'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_clay_definition_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///clay_definition.tcl',
        'package require clay\n'
        'clay::define ::demo {\n'
        '    superclass ::clay::object\n'
        '    constructor {name} {\n'
        '        my variable seen\n'
        '        set seen $name\n'
        '    }\n'
        '    method greet {who} {\n'
        '        return $who\n'
        '    }\n'
        '    Ensemble uri::add {vhosts patterns info} {\n'
        '        return [list $vhosts $patterns $info]\n'
        '    }\n'
        '    Dict reply {}\n'
        '    clay set plugin/ load {}\n'
        '}\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['clay::define'] == 'resolved'
    assert resolution_by_name['superclass'] == 'resolved'
    assert resolution_by_name['constructor'] == 'resolved'
    assert resolution_by_name['method'] == 'resolved'
    assert resolution_by_name['Ensemble'] == 'resolved'
    assert resolution_by_name['Dict'] == 'resolved'
    assert resolution_by_name['clay'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_resolves_clay_class_create_body_commands(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///clay_class_create.tcl',
        'package require clay\n'
        'clay::class create ::demo::Widget {\n'
        '    method greet {who} {\n'
        '        return $who\n'
        '    }\n'
        '}\n',
    )
    analysis = snapshot.analysis

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['clay::class'] == 'resolved'
    assert resolution_by_name['method'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_collects_tepam_procedures_from_package_metadata(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tepam_proc.tcl',
        'package require tepam\n'
        'tepam::procedure warn {\n'
        '    -args {\n'
        '        {-mtype -default Warning}\n'
        '        {text -type string}\n'
        '        {-verbose -type none}\n'
        '    }\n'
        '} {\n'
        '    puts $mtype\n'
        '    puts $text\n'
        '    if {$verbose} {\n'
        '        puts verbose\n'
        '    }\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert '::warn' in {procedure.qualified_name for procedure in facts.procedures}

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['tepam::procedure'] == 'resolved'

    variable_resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolution_by_name['mtype'] == 'resolved'
    assert variable_resolution_by_name['text'] == 'resolved'
    assert variable_resolution_by_name['verbose'] == 'resolved'
    assert analysis.diagnostics == ()


def test_analysis_collects_imported_tepam_procedures(parser: Parser) -> None:
    snapshot = _analyze(
        parser,
        'file:///tepam_imported_proc.tcl',
        'package require tepam\n'
        'namespace import ::tepam::*\n'
        'procedure {display message} {\n'
        '    -args {\n'
        '        {-title -default Hello}\n'
        '        {text -type string}\n'
        '    }\n'
        '} {\n'
        '    puts $title\n'
        '    puts $text\n'
        '}\n',
    )
    facts = snapshot.facts
    analysis = snapshot.analysis

    assert '::display message' in {procedure.qualified_name for procedure in facts.procedures}

    resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'command'
    }
    assert resolution_by_name['procedure'] == 'resolved'

    variable_resolution_by_name = {
        resolution.reference.name: resolution.uncertainty.state
        for resolution in analysis.resolutions
        if resolution.reference.kind == 'variable'
    }
    assert variable_resolution_by_name['title'] == 'resolved'
    assert variable_resolution_by_name['text'] == 'resolved'
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
        'package require Tk\nbind . <Escape> {destroy .}\nfont families\ntkwait visibility .\n',
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
        'proc run {n} {\n    set p($n) ok\n    puts $p($n)\n}\n',
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
        'proc run {n} {\n    set p($n)suffix ok\n    puts $p\n}\n',
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
        diagnostic.code
        for diagnostic in analysis.diagnostics
        if diagnostic.code == 'unresolved-variable'
    ]
    assert diagnostics == ['unresolved-variable']
