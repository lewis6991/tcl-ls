# Project configuration commands, selected automatically in tcllsrc.tcl.
meta module TclLSConfig {

    # Syntax: one positional path.
    #
    # Include static metadata or configuration declarations at this point.
    # Relative paths start in this config file's directory.
    # Included files inherit the enclosing metadata module, if present.
    #
    # **Example**
    #
    # ```tcl
    # source .tcl-ls/project.meta.tcl
    # ```
    meta override source {<path>}

    # Syntax: one positional path.
    #
    # Search this directory for Tcl package indexes.
    # Relative paths start in this config file's directory.
    # `library-path` is an alias with the same behavior.
    #
    # **Example**
    #
    # ```tcl
    # lib-path vendor/tcllib
    # ```
    meta command lib-path {path}
    meta alias library-path lib-path

    # Syntax: a module name, literal `when`, and a braced expression.
    #
    # Activate the metadata module when the expression is known to be true.
    # The expression is analyzed statically; it is never executed.
    # An unknown or false result does not activate the module.
    #
    # **Example**
    #
    # ```tcl
    # module ExampleTool when {$::tool eq "example"}
    # ```
    meta command module {name =when condition}

    # Syntax: positional code and level, with optional `-path pattern`.
    #
    # Code patterns can use wildcards. Later matching rules take precedence.
    #
    # **Levels (choose one)**
    #
    # - `error`, `warning`, `information`, `hint`: set the severity.
    # - `off`: suppress this diagnostic.
    # - `default`: restore the diagnostic's original severity.
    #
    # **Options**
    #
    # - `-path pattern`: select files or directories relative to this config.
    #   `*` stays in one component; `**` spans zero or more components.
    #   Absolute paths and `..` are not allowed.
    #   Default: all files in this config's scope.
    #
    # **Example**
    #
    # ```tcl
    # diagnostic unresolved-command off -path vendor/**
    # ```
    meta command diagnostic {code level ? -path pattern ?} {
        option -path value
    }
}
