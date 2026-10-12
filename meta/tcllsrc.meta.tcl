# Project configuration commands, selected automatically in tcllsrc.tcl.
meta module TclLSConfig {

    # Include a file of static metadata or configuration declarations.
    # Relative paths start in this config file's directory.
    meta override source {path}

    # Search this directory for Tcl package indexes.
    # Relative paths start in this config file's directory.
    meta command lib-path {path}
    meta alias library-path lib-path

    # Select a metadata module when this expression is known to be true.
    # The condition is analyzed statically and is never executed.
    meta command module {name =when condition}

    # Set a diagnostic severity: error, warning, information, hint, off, or default.
    # Code patterns can use wildcards. Optional paths select files or directories
    # relative to this config file; ** spans zero or more directory components.
    meta command diagnostic {code level ? -path pattern ?} {
        option -path value
    }
}
