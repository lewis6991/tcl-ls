# Tepam package command metadata for tcl-ls.
meta module tepam {
    # Declare a procedure using Tepam's attribute DSL.
    meta command tepam::procedure {name attributes body} {
        procedure {
            name {select 1}
            params {
                select 2
                plugin {tepam-plugin.tcl ::tepam::metadata::header_parameters}
            }
            body {select 3}
        }
    }
}
