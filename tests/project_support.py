from __future__ import annotations

from pathlib import Path


def write_sample_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'sample.tcl'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::procedure {words info} {\n'
        '    if {[llength $words] < 4} {\n'
        '        return {}\n'
        '    }\n'
        '    return [list [list procedure [format {\n'
        '        name select 2\n'
        '        params literal %s\n'
        '        _params-source select 3\n'
        '        body select 4\n'
        '    } [list [::tcl_lsp::plugins::sample::parameterNames [lindex $words 2]]]]]]\n'
        '}\n'
        'proc ::tcl_lsp::plugins::sample::parameterNames {parameter_list} {\n'
        '    set names {}\n'
        '    if {[catch {\n'
        '        foreach arg_def $parameter_list {\n'
        '            set name [lindex $arg_def 0]\n'
        '            if {$name eq ""} {\n'
        '                continue\n'
        '            }\n'
        '            lappend names $name\n'
        '        }\n'
        '    }]} {\n'
        '        return {}\n'
        '    }\n'
        '    return $names\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'sample.meta.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        '# Define a procedure using a project-local wrapper command.\n'
        'meta command dsl::define {name params body} {\n'
        '    plugin sample.tcl ::tcl_lsp::plugins::sample::procedure\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path


def write_sample_library_root(library_root: Path) -> Path:
    package_root = library_root / 'modules' / 'samplelib'
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / 'pkgIndex.tcl').write_text(
        'package ifneeded samplelib 1.0 [list source [file join $dir samplelib.tcl]]\n',
        encoding='utf-8',
    )
    (package_root / 'samplelib.tcl').write_text(
        'package provide samplelib 1.0\nproc samplelib::greet {} {return ok}\n',
        encoding='utf-8',
    )
    return package_root


def write_transitive_package_workspace(workspace_root: Path) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / 'pkgIndex.tcl').write_text(
        'package ifneeded helper 1.0 [list source [file join $dir helper.tcl]]\n',
        encoding='utf-8',
    )
    (workspace_root / 'helper.tcl').write_text(
        'package require json\npackage provide helper 1.0\n',
        encoding='utf-8',
    )
    source_path = workspace_root / 'main.tcl'
    source_path.write_text(
        'package require helper\njson::json2dict {}\n',
        encoding='utf-8',
    )
    return source_path


def write_declaration_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'declaration.tcl'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::declaration {words info} {\n'
        '    if {[llength $words] < 3} {\n'
        '        return {}\n'
        '    }\n'
        '    return [list [list procedure [format {\n'
        '        name select 2\n'
        '        params literal %s\n'
        '        _params-source select 3\n'
        '    } [list [::tcl_lsp::plugins::sample::parameterNames [lindex $words 2]]]]]]\n'
        '}\n'
        'proc ::tcl_lsp::plugins::sample::parameterNames {parameter_list} {\n'
        '    set names {}\n'
        '    if {[catch {\n'
        '        foreach arg_def $parameter_list {\n'
        '            set name [lindex $arg_def 0]\n'
        '            if {$name eq ""} {\n'
        '                continue\n'
        '            }\n'
        '            lappend names $name\n'
        '        }\n'
        '    }]} {\n'
        '        return {}\n'
        '    }\n'
        '    return $names\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'declaration.meta.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        '# Declare a procedure using a project-local wrapper command.\n'
        'meta command dsl::declare {name params} {\n'
        '    plugin declaration.tcl ::tcl_lsp::plugins::sample::declaration\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path


def write_effect_clause_plugin_bundle(metadata_root: Path) -> Path:
    metadata_root.mkdir(parents=True, exist_ok=True)
    plugin_path = metadata_root / 'effects.tcl'
    plugin_path.write_text(
        'namespace eval ::tcl_lsp::plugins::sample {}\n'
        'proc ::tcl_lsp::plugins::sample::effects {words info} {\n'
        '    switch -- [dict get $info metadata-command] {\n'
        '        dsl::run {\n'
        '            if {[llength $words] < 4} {\n'
        '                return {}\n'
        '            }\n'
        '            return [list \\\n'
        '                [list bind 2 set] \\\n'
        '                [list source 3 caller] \\\n'
        '                [list package literal TclOO] \\\n'
        '                [list enter tcl body 4] \\\n'
        '            ]\n'
        '        }\n'
        '        dsl::use {\n'
        '            if {[llength $words] < 2} {\n'
        '                return {}\n'
        '            }\n'
        '            return [list [list ref 2]]\n'
        '        }\n'
        '        dsl::loadlist {\n'
        '            if {[llength $words] < 2} {\n'
        '                return {}\n'
        '            }\n'
        '            return [list [list source list 2 caller]]\n'
        '        }\n'
        '    }\n'
        '    return {}\n'
        '}\n',
        encoding='utf-8',
    )
    (metadata_root / 'effects.meta.tcl').write_text(
        '# Project metadata loaded from project-local plugin configuration.\n'
        'meta module Tcl\n'
        'meta command dsl::run {name helper body} {\n'
        '    plugin effects.tcl ::tcl_lsp::plugins::sample::effects\n'
        '}\n'
        'meta command dsl::use {name} {\n'
        '    plugin effects.tcl ::tcl_lsp::plugins::sample::effects\n'
        '}\n'
        'meta command dsl::loadlist {paths} {\n'
        '    plugin effects.tcl ::tcl_lsp::plugins::sample::effects\n'
        '}\n',
        encoding='utf-8',
    )
    return plugin_path
