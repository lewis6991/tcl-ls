namespace eval ::tcl_lsp::plugin_host {
    variable command_limit 50000
    variable safe_commands_to_hide {
        after
        chan
        close
        eof
        fileevent
        flush
        gets
        interp
        package
        puts
        read
        seek
        tell
        update
        vwait
    }
    variable interp_counter 0

    proc decode {line} {
        return [encoding convertfrom utf-8 [binary decode base64 $line]]
    }

    proc encode {text} {
        return [binary encode base64 -maxlen 0 [encoding convertto utf-8 $text]]
    }

    proc read_line {} {
        if {[gets stdin line] < 0} {
            error "Unexpected end of Tcl plugin input."
        }
        return $line
    }

    proc read_int {} {
        set line [read_line]
        if {![string is integer -strict $line]} {
            error "Expected integer plugin host field, got `$line`."
        }
        return $line
    }

    proc read_b64 {} {
        return [decode [read_line]]
    }

    proc read_dict {} {
        set count [read_int]
        set values {}
        for {set index 0} {$index < $count} {incr index} {
            dict set values [read_b64] [read_b64]
        }
        return $values
    }

    proc respond {status payload} {
        puts stdout $status
        puts stdout [encode $payload]
        flush stdout
    }

    proc configure_interp {safe_interp} {
        variable command_limit
        variable safe_commands_to_hide

        interp limit $safe_interp command -value $command_limit

        foreach command_name $safe_commands_to_hide {
            catch {interp hide $safe_interp $command_name}
        }
        interp eval $safe_interp {
            if {[llength [info commands unknown]] != 0} {
                rename unknown {}
            }
            set auto_path {}
            catch {unset auto_index}
            array set auto_index {}
            namespace eval ::tcl_lsp {}
        }

        foreach {name operation} {
            word word
            variable variable
            source_list_items source-list-items
            slice slice
        } {
            interp alias $safe_interp ::tcl_lsp::$name {} \
                ::tcl_lsp::plugin_host::query $operation
        }
    }

    proc query {operation args} {
        puts stdout query
        puts stdout [expr {1 + [llength $args]}]
        foreach value [list $operation {*}$args] {
            puts stdout [encode $value]
        }
        flush stdout
        set status [read_line]
        set payload [read_b64]
        if {$status ne "ok"} {
            error $payload
        }
        return $payload
    }

    proc with_plugin_interp {script_label script_source proc_name argument info} {
        variable interp_counter

        set safe_interp [format "::tcl_lsp::plugin_host::safe_%d" [incr interp_counter]]
        interp create -safe $safe_interp
        try {
            configure_interp $safe_interp
            interp eval $safe_interp $script_source
            if {[llength [interp eval $safe_interp [list info procs $proc_name]]] == 0} {
                error "Plugin proc `$proc_name` was not defined by `$script_label`."
            }
            return [interp eval $safe_interp [list $proc_name $argument $info]]
        } finally {
            catch {interp delete $safe_interp}
        }
    }

    proc handle_call {} {
        set script_label [read_b64]
        set script_source [read_b64]
        set proc_name [read_b64]
        set argument [read_b64]
        set info [read_dict]

        return [with_plugin_interp $script_label $script_source $proc_name $argument $info]
    }

    proc run {} {
        while {[gets stdin opcode] >= 0} {
            switch -- $opcode {
                call {
                    if {[catch {handle_call} result]} {
                        respond error $result
                        continue
                    }
                    respond ok $result
                }
                quit {
                    return
                }
                default {
                    respond error "Unknown Tcl plugin host opcode `$opcode`."
                }
            }
        }
    }
}

::tcl_lsp::plugin_host::run
