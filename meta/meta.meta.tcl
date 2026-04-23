# Metadata command format for tcl-ls.
#
# Metadata files use the `meta` ensemble for structured declarations instead of
# executable behavior and conventionally use the `.meta.tcl` suffix.
#
# This comment block describes the current metadata syntax.
# Optional outer grammar is described with separate forms and prose below.
# Literal `?` words only appear inside `shape` lists.
meta module Tcl
#
# Top-level declarations:
#   meta module name
#   meta command name {shape}
#   meta command name {shape} {
#       clause ...
#   }
#   meta command name variants {
#       form {shape}
#       form {shape} {
#           clause ...
#       }
#       command name {shape}
#       command name {shape} {
#           clause ...
#       }
#       command name variants { ... }
#   }
#   meta language languageName {
#       command name {shape}
#       command name {shape} {
#           clause ...
#       }
#       command name variants {
#           form {shape}
#           form {shape} {
#               clause ...
#           }
#           command name {shape}
#           command name {shape} {
#               clause ...
#           }
#           command name variants { ... }
#       }
#   }
#   `extends tcl` is an optional ordinary clause inside a `meta language` body.
#
# `name` is a single command word. Nested command words must be declared with
# `command`.
#
# `shape` is the structural form of one callable command shape. It is not
# display-only text. Single-form commands may elide `form`; commands that use
# explicit `form` entries should use `variants`. `variants` blocks must still
# declare at least one `form`; nested `command` entries only add child nodes.
#
# Shape syntax:
#   A shape is a Tcl list.
#   Plain words like `varName` or `script` are descriptive placeholders for one
#   argument position.
#   Standalone `?` items wrap an optional group, so `? newValue ?` means that
#   position may be omitted.
#   `args` consumes the remaining arguments and must be the final shape item.
#   Words prefixed with `=` are exact literals.
#   A grouped Tcl word still counts as one argument position.
#   `{name default}` is Tcl's defaulted-argument form for one optional
#   position and is the natural spelling when the API already follows Tcl
#   parameter-list notation.
#   Angle-bracket names like `<name>` and `<selector>` only appear in this
#   self-describing grammar; ordinary metadata does not use angle brackets in
#   everyday command shapes.
#   Generated metadata may normalize simple optional arguments to `? ... ?`.
#
# Clause bodies:
#   A command body is a static Tcl command list, usually written as a braced
#   block. Each nested command in the block is one sibling clause.
#
#   Example:
#       meta command regexp {args} {
#           option -all
#           option -start value
#           option -- stop
#           bind after-options 3.. regexp
#       }
#
# Selector syntax:
#   Selectors point at arguments in the declared shape using positive
#   1-based positions.
#
#   1               the first argument
#   3..             the third argument through the end
#   2..5            arguments 2 through 5 inclusive
#   last            the final argument
#   last-1          the argument before the final argument
#   1..last-1       arguments 1 through the argument before the final argument
#   list 2          split argument 2 as a Tcl list and select each item
#   1..last-1 step 2
#                   select every second argument in the chosen range
#   after-options 2 resolve the second positional argument after known options
#
# Annotation reference:
#
# option name
#   Declare a known flag option that takes no value.
#
# option name value
#   Declare a known option that consumes one following value.
#
# option -- stop
#   Declare `--` as the end of option parsing for this command.
#
# command name {shape}
# command name {shape} { annotation ... }
# command name variants { ... }
#   Declare a nested command using the same shape as `meta command`. The
#   declared name also contributes to the parent's command tree.
#
# bind selector
# bind selector kind
#   Treat the selected argument as the name of a variable binding introduced by
#   this command. `kind` is optional when it can be inferred from the command
#   name tail; otherwise it should be explicit.
#
# ref selector
#   Treat the selected argument as the name of a variable reference.
#
# enter language body selector
# enter language body selector owner selector
#   Enter the named embedded command language for the selected body argument or
#   arguments. The body selector must be a direct contiguous range. Structured
#   Tcl commands lowered specially by tcl-ls (`proc`, `namespace eval`, `for`,
#   `if`, `catch`, `try`, `switch`, and `while`) only allow one existing
#   script-body argument per `enter`. `owner` is optional and must select one
#   direct argument. Use `enter tcl body ...` for Tcl bodies.
#
# source selector caller
# source selector definition
#   Treat the selected arguments as paths that should be resolved and loaded as
#   source dependencies. `caller` resolves relative to the file containing the
#   call site. `definition` resolves relative to the helper definition.
#
# package literal packageName
# package select selector
#   Treat the command as requiring a package. The fixed literal case stays
#   terse, while `select` reads the package name from an argument.
#
# procedure { ... }
#   Declare a procedure-like command shape using tagged field values:
#       name select selector | literal value | -
#           `-` reuses the enclosing command name tail.
#       params select selector | literal parameterList | -
#           `literal` uses ordinary Tcl procedure parameter-list syntax:
#           names, `{name default}` items, and optional trailing `args`.
#           `-` means the emitted procedure has no parameters.
#       body select selector
#           `select` must choose exactly one argument.
#       language name            # only when `body` is present
#
# plugin script procName
#   Run a Tcl plugin to produce dynamic metadata effects. Plugins may return
#   only the dynamic effect subset:
#       bind selector kind
#       ref selector
#       enter language body selector
#       enter language body selector owner selector
#       package literal packageName
#       package select selector
#       source selector caller|definition
#       procedure { ... }
#   Plugin `procedure` effects reuse the declarative `name`/`params`/`body`/
#   `language` fields and may additionally include `_params-source select
#   selector` when literal parameters need a source anchor. Plugin selectors
#   apply to the full command word list and do not support `after-options`.
#
# extends tcl
#   Allow the embedded language to include ordinary Tcl command
#   resolution after checking its explicit `command` declarations. Languages
#   without `extends tcl` are closed and only accept their declared commands.
#
# A command can use multiple clauses in one body when needed.
#
# Declare metadata for Tcl language entities.
# Tcl-ls treats this as structured documentation instead of executable
# behavior. `meta` is an ensemble whose subcommands describe command metadata
# and embedded command languages.
meta command meta {subcommand args} {
    # Declare the builtin package or module represented by this metadata file.
    # Files with a `meta module` declaration are indexed as bundled package
    # metadata.
    command module {<name>}

    # Declare metadata for a command or command prefix.
    # Use `meta command name {shape}` for single-form commands, or
    # `meta command name variants { ... }` for explicit `form` and nested
    # `command` declarations.
    command command variants {
        form {<name> <shape>}
        form {<name> <groupedShape> <body>} {
            enter meta-command-body body 3
        }
        form {<name> =variants <body>} {
            enter meta-command-body body 3
        }
    }

    # Declare an embedded command language and the commands valid within it.
    # The body contains `command name {shape}` or
    # `command name variants { ... }` entries that are only valid while a
    # matching `enter` clause is active.
    command language {<name> <body>} {
        enter meta-language-body body 2
    }
}

meta language meta-command-body {
    command option variants {
        form {<name>}
        form {<name> <value>}
        form {=-- =stop}
    }

    command command variants {
        form {<name> <shape>}
        form {<name> <groupedShape> <body>} {
            enter meta-command-body body 3
        }
        form {<name> =variants <body>} {
            enter meta-command-body body 3
        }
    }

    command form variants {
        form {<shape>}
        form {<groupedShape> <body>} {
            enter meta-command-body body 2
        }
    }

    command bind variants {
        form {<selector>}
        form {<selector> <kind>}
    }

    command ref {<selector>}

    command enter variants {
        form {<language> =body <bodySelector>}
        form {<language> =body <bodySelector> =owner <ownerSelector>}
    }

    command source variants {
        form {<selector> =caller}
        form {<selector> =definition}
    }

    command package variants {
        form {=literal <packageName>}
        form {=select <selector>}
    }

    command procedure {<body>} {
        enter meta-procedure-body body 1
    }

    command plugin {<script> <procName>}
}

meta language meta-language-body {
    command extends variants {
        form {=tcl}
    }

    command command variants {
        form {<name> <shape>}
        form {<name> <groupedShape> <body>} {
            enter meta-command-body body 3
        }
        form {<name> =variants <body>} {
            enter meta-command-body body 3
        }
    }
}

meta language meta-procedure-body {
    command name variants {
        form {=select <procedureSelector>}
        form {=literal <value>}
        form {=-}
    }

    command params variants {
        form {=select <procedureSelector>}
        form {=literal <value>}
        form {=-}
    }

    command body {=select <procedureSelector>}

    command language {<name>}
}
