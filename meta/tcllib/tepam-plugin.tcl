# tcl-ls: module TclLSPlugin
# Read Tepam declarations as data. This script does not run the declared body.
namespace eval ::tepam::metadata {}

proc ::tepam::metadata::arguments {header} {
    set fields [::tcl_lsp::source_list_items $header]
    if {[llength $fields] % 2} {
        error "Tepam attributes must be key/value pairs"
    }

    set arguments {}
    foreach {key value} $fields {
        if {[dict get $key text] eq "-args"} {
            set arguments [::tcl_lsp::source_list_items $value]
        }
    }
    return $arguments
}

proc ::tepam::metadata::parameters {arguments} {
    set parameters {}
    foreach argument $arguments {
        set fields [::tcl_lsp::source_list_items $argument]
        if {![llength $fields]} {
            continue
        }

        set name [lindex $fields 0]
        set text [dict get $name text]
        if {[string index $text 0] eq "-"} {
            set name [::tcl_lsp::slice $name 1 end]
            set text [dict get $name text]
        }
        if {[regexp {^[A-Za-z0-9_:]+$} $text]} {
            lappend parameters [dict get $name id]
        }
    }
    return $parameters
}

proc ::tepam::metadata::header_parameters {header info} {
    if {[catch {parameters [arguments $header]} parameters]} {
        return {}
    }
    return [list items $parameters]
}
