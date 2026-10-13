# Model one caller-variable substitution pass in the wrapper's argument list.
# Inserted values stay literal. Commands and defaults are not evaluated.
proc ::tepam::metadata::expand {arguments} {
    set expanded {}
    set plain_variable {^\$((?:[A-Za-z0-9_]|::)+)$}
    set braced_variable {^\$\{([^\}\n]+)\}$}
    foreach argument $arguments {
        set text [dict get $argument text]
        if {[string index $text 0] ne "$" || [dict get $argument grouped]} {
            lappend expanded $argument
            continue
        }

        set name [lindex [regexp -inline $plain_variable $text] 1]
        if {$name eq ""} {
            set name [lindex [regexp -inline $braced_variable $text] 1]
        }
        if {$name eq ""} {
            error "Unresolved argument fragment"
        }

        set value [::tcl_lsp::variable $name]
        if {$value eq ""} {
            error "Unknown argument fragment"
        }
        lappend expanded {*}[::tcl_lsp::source_list_items $value]
    }
    return $expanded
}

proc ::tepam::metadata::shared {header info} {
    if {[catch {parameters [expand [arguments $header]]} parameters]} {
        return {}
    }
    return [list items $parameters]
}

proc ::tepam::metadata::declaration {header info} {
    return [header_parameters $header $info]
}

proc ::tepam::metadata::implementation {arguments info} {
    if {[catch {parameters [::tcl_lsp::source_list_items $arguments]} parameters]} {
        return {}
    }
    return [list items $parameters]
}
