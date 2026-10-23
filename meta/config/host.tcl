# Evaluate rc scripts in a fresh Tcl process. Registration bodies remain data.
namespace eval ::tcl_lsp::rc {
    variable events {}
    variable module {}
    variable stack {}
    variable offsets {0}
    variable output [open [lindex $::argv 0] w]
    fconfigure $output -encoding utf-8 -translation lf

    proc emit {kind args} {
        variable events
        lappend events [list $kind {*}$args]
    }

    proc location {} {
        variable stack
        variable offsets
        for {set level -2} {$level > -[info frame]} {incr level -1} {
            set frame [info frame $level]
            if {[dict exists $frame file] && [dict get $frame file] eq [lindex $stack end]} {
                return $frame
            }
            if {![dict exists $frame file] && [dict get $frame type] eq "eval"} {
                if {[string match {::tcl_lsp::rc::register *} [dict get $frame cmd]]} {
                    continue
                }
                dict set frame file [lindex $stack end]
                dict incr frame line [lindex $offsets end]
                return $frame
            }
        }
        return [dict create file [lindex $stack end] line 1 cmd {}]
    }

    proc error_location {options path} {
        set information [dict get $options -errorinfo]
        if {[regexp {\(file "([^\n]+)" line ([0-9]+)\)} $information -> file line]} {
            return [list $file $line]
        }
        if {[regexp {\("uplevel" body line ([0-9]+)\)} $information -> line]} {
            return [list $path $line]
        }
        return [list $path [dict get $options -errorline]]
    }

    proc register {name args} {
        variable module
        set frame [location]
        emit command [dict get $frame file] [dict get $frame line] \
            [dict get $frame cmd] $module $name {*}$args
    }

    proc source {args} {
        variable stack
        variable module
        if {[llength $args] ni {1 3} || ([llength $args] == 3 && [lindex $args 0] ne "-encoding")} {
            error {wrong # args: should be "source ?-encoding name? fileName"}
        }
        set target [lindex $args end]
        if {[file pathtype $target] ne "absolute" && [llength $stack]} {
            set target [file join [file dirname [lindex $stack end]] $target]
        }
        set target [file normalize $target]
        if {$target in $stack} {
            error "Metadata include cycle: [join [list {*}$stack $target] { -> }]"
        }
        set frame [location]
        emit enter $target $module [dict get $frame file] [dict get $frame line] [dict get $frame cmd]
        lappend stack $target
        try {
            uplevel 1 [list ::tcl_lsp::rc::native_source {*}[lrange $args 0 end-1] $target]
        } on error {message options} {
            if {![dict exists $options -rc-location]} {
                dict set options -rc-location [error_location $options $target]
            }
            return -options $options $message
        } finally {
            set stack [lrange $stack 0 end-1]
            emit leave
        }
    }

    proc meta {args} {
        variable module
        if {[lindex $args 0] ne "module"} {
            uplevel 1 [list ::tcl_lsp::rc::register meta {*}$args]
            return
        }
        if {[llength $args] != 3 || [lindex $args 1] eq ""} {
            error {Module declarations must be `meta module name {body}`.}
        }
        set outer $module
        set module [lindex $args 1]
        set frame [location]
        emit scope [dict get $frame file] $module
        try {
            eval_body [lindex $args 2] $frame
        } finally {
            set module $outer
            emit scope [dict get $frame file] $module
        }
    }

    proc eval_body {body frame} {
        variable offsets
        set start [string last $body [dict get $frame cmd]]
        set prefix [string range [dict get $frame cmd] 0 [expr {$start - 1}]]
        set offset [expr {[dict get $frame line] - 1 + [regexp -all {\n} $prefix]}]
        lappend offsets $offset
        try {
            uplevel 2 $body
        } on error {message options} {
            if {![dict exists $options -rc-location]} {
                set line [dict get $frame line]
                if {[regexp {\("uplevel" body line ([0-9]+)\)} [dict get $options -errorinfo] -> relative]} {
                    set line [expr {$offset + $relative}]
                }
                dict set options -rc-location [list [dict get $frame file] $line]
            }
            return -options $options $message
        } finally {
            set offsets [lrange $offsets 0 end-1]
        }
    }

    proc file_probe {command operation} {
        set kind [lindex $command 1]
        if {$kind in {exists isfile isdirectory readable writable executable size mtime atime stat lstat type owned}} {
            emit probe [file normalize [lindex $command 2]]
        }
    }

    proc open_probe {command operation} {
        if {[string index [lindex $command 1] 0] ne "|"} {
            emit probe [file normalize [lindex $command 1]]
        }
    }

    proc glob_probe {command operation} {
        # Globs may examine directories which are absent from their result.
        # Re-evaluate these scripts rather than reuse an incomplete dependency set.
        emit volatile
    }
}

namespace eval ::tcl_lsp {
    variable context [dict create \
        workspace-root [lindex $::argv 2] \
        config-path [lindex $::argv 1]]
}
rename ::source ::tcl_lsp::rc::native_source
interp alias {} ::source {} ::tcl_lsp::rc::source
interp alias {} ::meta {} ::tcl_lsp::rc::meta
foreach name {lib-path library-path exclude module diagnostic} {
    interp alias {} ::$name {} ::tcl_lsp::rc::register $name
}
trace add execution ::file enter ::tcl_lsp::rc::file_probe
trace add execution ::open enter ::tcl_lsp::rc::open_probe
trace add execution ::glob enter ::tcl_lsp::rc::glob_probe

set ::tcl_lsp::rc::stack [list [lindex $::argv 1]]
set status [catch {
    if {[lindex $::argv 3]} {
        # Source an editor buffer without changing the saved file.
        set script [lindex $::argv 4]
        set previous [info script]
        info script [lindex $::argv 1]
        try {uplevel #0 $script} finally {info script $previous}
    } else {
        ::tcl_lsp::rc::native_source [lindex $::argv 1]
    }
} message options]
if {$status == 1} {
    set location [::tcl_lsp::rc::error_location $options [lindex $::argv 1]]
    if {[dict exists $options -rc-location]} {
        set location [dict get $options -rc-location]
    }
    ::tcl_lsp::rc::emit error {*}$location $message
}
::tcl_lsp::rc::emit done
foreach event $::tcl_lsp::rc::events {
    set fields [lmap value $event {
        binary encode base64 -maxlen 0 [encoding convertto utf-8 $value]
    }]
    puts $::tcl_lsp::rc::output [join $fields :]
}
close $::tcl_lsp::rc::output
