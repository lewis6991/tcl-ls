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
        return [binary decode base64 $line]
    }

    proc encode {text} {
        return [binary encode base64 -maxlen 0 $text]
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

    proc read_list {} {
        set count [read_int]
        set values {}
        for {set index 0} {$index < $count} {incr index} {
            lappend values [read_b64]
        }
        return $values
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
        }
    }

    proc with_plugin_interp {script_label script_source proc_name words info} {
        variable interp_counter

        set safe_interp [format "::tcl_lsp::plugin_host::safe_%d" [incr interp_counter]]
        interp create -safe $safe_interp
        try {
            configure_interp $safe_interp
            interp eval $safe_interp $script_source
            if {[llength [interp eval $safe_interp [list info procs $proc_name]]] == 0} {
                error "Plugin proc `$proc_name` was not defined by `$script_label`."
            }
            return [interp eval $safe_interp [list $proc_name $words $info]]
        } finally {
            catch {interp delete $safe_interp}
        }
    }

    proc handle_call {} {
        set script_label [read_b64]
        set script_source [read_b64]
        set proc_name [read_b64]
        set words [read_list]
        set info [read_dict]

        return [with_plugin_interp $script_label $script_source $proc_name $words $info]
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
