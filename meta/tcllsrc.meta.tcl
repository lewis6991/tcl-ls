# Project configuration commands, selected automatically in tcllsrc.tcl.
meta module TclLSConfig {

    # Syntax: one positional path.
    #
    # Evaluate a Tcl metadata or configuration file at this point.
    # Relative paths start in this config file's directory.
    # Included files inherit the enclosing metadata module, if present.
    # Paths can use Tcl variables and command substitutions.
    # `$::tcl_lsp::context` gives the workspace root and config path.
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

    # Syntax: one positional path.
    #
    # Skip this file or directory when discovering sources and package indexes.
    # Relative paths start in this config file's directory.
    # A directory excludes all its descendants. Paths are literal, without globs.
    # Explicitly opened files and source dependencies are still analyzed.
    #
    # **Example**
    #
    # ```tcl
    # exclude .venv
    # ```
    meta command exclude {path}

    # Syntax: a module name, optionally followed by `when` and a braced expression.
    #
    # Without `when`, activate the module throughout this config's source scope.
    # With `when`, activate it only where the expression is known to be true.
    # The expression is analyzed statically; it is never executed.
    # An unknown or false result does not activate the module.
    #
    # **Example**
    #
    # ```tcl
    # module ExampleTool
    # module ExampleTool when {$::tool eq "example"}
    # ```
    meta command module {name ? =when condition ?}

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
