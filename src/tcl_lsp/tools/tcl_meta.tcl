#!/usr/bin/env tclsh

# Source this file inside a tool Tcl interpreter and run:
#     tcl-meta build-file path/to/metadata.meta.tcl
#
# The helper introspects the current Tcl environment, diffs its command set
# against a plain child `tclsh`, and writes generic `meta command` /
# `subcommand` declarations for the newly introduced command roots.

namespace eval ::tcl_meta {
    variable script_path [file normalize [info script]]
    variable probe_token __tcl_meta_probe__
    variable max_depth 6

    proc usage {} {
        error "usage: tcl-meta command-list | build-file output-path"
    }

    proc normalize_command_name {name} {
        if {[string match ::* $name]} {
            return [string range $name 2 end]
        }
        return $name
    }

    proc resolved_command_name {name} {
        set resolved [namespace which -command $name]
        if {$resolved eq ""} {
            set resolved $name
        }
        return [normalize_command_name $resolved]
    }

    proc should_keep_command {name} {
        set normalized [resolved_command_name $name]
        if {$normalized eq "" || $normalized eq "tcl-meta"} {
            return 0
        }
        if {[string match "tcl_meta::*" $normalized]} {
            return 0
        }
        return 1
    }

    proc command_list {} {
        set commands {}
        foreach command [info commands] {
            if {[should_keep_command $command]} {
                lappend commands [resolved_command_name $command]
            }
        }

        set todo [namespace children ::]
        while {[llength $todo] > 0} {
            set ns [lindex $todo 0]
            set todo [lrange $todo 1 end]
            if {$ns eq "::tcl_meta"} {
                continue
            }
            if {$ns ne "::oo"} {
                set todo [concat $todo [namespace children $ns]]
            }

            set exports [namespace eval $ns {namespace export}]
            if {[llength $exports] == 0} {
                set exports [list {[a-z]*}]
            }
            foreach pat $exports {
                foreach command [info commands ${ns}::$pat] {
                    if {[should_keep_command $command]} {
                        lappend commands [resolved_command_name $command]
                    }
                }
            }
        }
        return [lsort -unique -dictionary $commands]
    }

    proc normalize_choices {text} {
        regsub {^one of } $text {} text
        set text [string map [list \" {} \' {}] $text]
        regsub -all {(, or )|( or )|(, )} $text { } text

        set candidates {}
        foreach word $text {
            set candidate [string trim $word {,.}]
            if {$candidate eq ""} {
                continue
            }
            if {[string match "-*" $candidate]} {
                continue
            }
            if {![regexp {^[-[:alnum:]_:.]+$} $candidate]} {
                continue
            }
            lappend candidates $candidate
        }
        return [lsort -unique -dictionary $candidates]
    }

    proc choice_list_from_error {message} {
        foreach pattern {
            {unknown or ambiguous subcommand .*: must be (.*)$}
            {unknown subcommand .*: must be (.*)$}
            {bad subcommand .*: must be (.*)$}
            {bad option .*: must be (.*)$}
            {option .* must be (.*)$}
            {option .* should be one of (.*)$}
            {bad .* must be (.*)$}
            {: must be (.*)$}
            {: should be (.*)$}
        } {
            if {[regexp $pattern $message -> choices]} {
                return [normalize_choices $choices]
            }
        }
        return {}
    }

    proc probe_subcommands {path_words} {
        variable probe_token
        set probe_words [concat $path_words [list $probe_token]]
        if {![catch {uplevel #0 $probe_words} message]} {
            return {}
        }
        return [choice_list_from_error $message]
    }

    proc subcommand_map {command_names} {
        variable max_depth
        set mapping {}
        set queue {}
        set seen {}

        foreach command $command_names {
            lappend queue [list $command]
        }

        while {[llength $queue] > 0} {
            set path_words [lindex $queue 0]
            set queue [lrange $queue 1 end]

            set path [join $path_words { }]
            if {[dict exists $seen $path]} {
                continue
            }
            dict set seen $path 1

            if {[llength $path_words] > $max_depth} {
                continue
            }

            set children [probe_subcommands $path_words]
            if {[llength $children] == 0} {
                continue
            }

            dict set mapping $path $children
            if {[llength $path_words] == $max_depth} {
                continue
            }
            foreach child $children {
                lappend queue [concat $path_words [list $child]]
            }
        }
        return $mapping
    }

    proc new_command_set {baseline_commands current_commands} {
        set baseline_lookup {}
        foreach command $baseline_commands {
            dict set baseline_lookup $command 1
        }

        set result {}
        foreach command $current_commands {
            if {[dict exists $baseline_lookup $command]} {
                continue
            }
            dict set result $command 1
        }
        return $result
    }

    proc lookup_subcommands {subcommand_map path} {
        if {![dict exists $subcommand_map $path]} {
            return {}
        }
        return [dict get $subcommand_map $path]
    }

    proc absolute_command_name {name} {
        if {[string match ::* $name]} {
            return $name
        }
        return ::$name
    }

    proc proc_signature {name signature_var} {
        upvar 1 $signature_var signature

        set command [absolute_command_name $name]
        if {[catch {info args $command} parameters]} {
            return 0
        }

        set signature {}
        set last_index [expr {[llength $parameters] - 1}]
        for {set index 0} {$index < [llength $parameters]} {incr index} {
            set parameter [lindex $parameters $index]
            if {[catch {info default $command $parameter default_value} has_default]} {
                return 0
            }

            # `args` is only representable in metadata when it keeps Tcl's
            # usual trailing varargs meaning.
            if {$parameter eq "args"} {
                if {!$has_default && $index == $last_index} {
                    lappend signature args
                    continue
                }
                return 0
            }

            if {$has_default} {
                lappend signature ? $parameter ?
                continue
            }

            lappend signature $parameter
        }

        return 1
    }

    proc command_signature {name has_children} {
        if {[proc_signature $name signature]} {
            return $signature
        }
        if {$has_children} {
            return {subcommand args}
        }
        return {args}
    }

    proc emit_subcommand {ch subcommand_map path indent} {
        set segment [lindex [split $path] end]
        set children [lookup_subcommands $subcommand_map $path]
        if {[llength $children] == 0} {
            puts $ch "${indent}subcommand [list $segment] {args}"
            return
        }

        puts $ch "${indent}subcommand [list $segment] {subcommand args} {"
        foreach child $children {
            emit_subcommand $ch $subcommand_map "$path $child" "    $indent"
        }
        puts $ch "${indent}}"
    }

    proc emit_root_command {ch subcommand_map command} {
        set children [lookup_subcommands $subcommand_map $command]
        set signature [command_signature $command [expr {[llength $children] != 0}]]
        if {[llength $children] == 0} {
            puts $ch "meta command [list $command] [list $signature]"
            return
        }

        puts $ch "meta command [list $command] [list $signature] {"
        foreach child $children {
            emit_subcommand $ch $subcommand_map "$command $child" "    "
        }
        puts $ch "}"
    }

    proc write_metadata {output_path new_commands subcommand_map} {
        file mkdir [file dirname $output_path]
        set ch [open $output_path w]
        try {
            puts $ch "# Generated by tcl-meta build-file."
            puts $ch "# Contains commands discovered from the active tool Tcl environment."
            puts $ch "meta module Tcl"
            puts $ch ""

            foreach command [lsort -dictionary [dict keys $new_commands]] {
                emit_root_command $ch $subcommand_map $command
            }
        } finally {
            close $ch
        }
    }

    proc baseline_commands {} {
        variable script_path
        if {$script_path eq ""} {
            error "tcl-meta build-file requires this helper to be sourced from a file"
        }

        set tclsh_cmd [auto_execok tclsh]
        if {$tclsh_cmd eq ""} {
            error "tcl-meta build-file requires `tclsh` on PATH"
        }

        set command [concat $tclsh_cmd [list $script_path command-list]]
        return [exec {*}$command]
    }

    proc build_file {output_path} {
        set current_commands [command_list]
        set baseline_commands [baseline_commands]
        set new_commands [new_command_set $baseline_commands $current_commands]
        set subcommand_map [subcommand_map [lsort -dictionary [dict keys $new_commands]]]
        write_metadata $output_path $new_commands $subcommand_map
    }

    proc dispatch {subcommand args} {
        switch -- $subcommand {
            command-list {
                if {[llength $args] != 0} {
                    usage
                }
                puts [command_list]
            }
            build-file {
                if {[llength $args] != 1} {
                    usage
                }
                build_file [lindex $args 0]
            }
            default {
                usage
            }
        }
    }
}

proc tcl-meta {subcommand args} {
    tailcall ::tcl_meta::dispatch $subcommand {*}$args
}

if {[info exists ::argv0] && [file normalize $::argv0] eq $::tcl_meta::script_path} {
    if {$::argc < 1} {
        puts stderr "usage: tcl_meta.tcl command-list | build-file output-path"
        exit 2
    }

    try {
        ::tcl_meta::dispatch {*}$::argv
    } on error {message} {
        puts stderr "error: $message"
        exit 1
    }
}
