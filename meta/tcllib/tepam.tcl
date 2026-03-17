namespace eval ::tcl_lsp::plugins::tepam {}

proc ::tcl_lsp::plugins::tepam::statementWords {words info} {
    if {[dict get $info metadata-command] ne "tepam::procedure"} {
        return {}
    }
    if {[llength $words] < 4} {
        return {}
    }

    set static_flags [dict get $info static-flags]
    foreach index {1 2 3} {
        if {[lindex $static_flags $index] ne "1"} {
            return {}
        }
    }

    set procedure_name [lindex $words 1]
    set attributes [lindex $words 2]
    if {$procedure_name eq "" || $attributes eq ""} {
        return {}
    }

    return [list [list procedure [dict create \
        name-index 1 \
        params-word-index 2 \
        params [::tcl_lsp::plugins::tepam::parameterNames $attributes] \
        body-index 3 \
    ]]]
}

proc ::tcl_lsp::plugins::tepam::parameterNames {attributes} {
    set names {}
    if {[catch {
        foreach {name value} $attributes {
            if {$name ne "-args"} {
                continue
            }
            foreach arg_def $value {
                set parameter_name [::tcl_lsp::plugins::tepam::parameterName $arg_def]
                if {$parameter_name eq ""} {
                    continue
                }
                lappend names $parameter_name
            }
        }
    }]} {
        return {}
    }
    return $names
}

proc ::tcl_lsp::plugins::tepam::parameterName {arg_def} {
    set name [lindex $arg_def 0]
    if {$name eq "" || $name in {"-" "--"}} {
        return ""
    }
    if {[string index $name 0] eq "#"} {
        return ""
    }
    if {[string index $name 0] eq "-"} {
        set name [string range $name 1 end]
    }
    if {![regexp {^[[:alnum:]_:]+$} $name]} {
        return ""
    }
    return $name
}
