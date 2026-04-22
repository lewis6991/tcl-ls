# Metadata command format for tcl-ls.
#
# Metadata files use the `meta` ensemble for structured declarations instead of
# executable behavior and conventionally use the `.meta.tcl` suffix.
#
# This comment block describes the current metadata syntax.
meta module Tcl
#
# Top-level declarations:
#   meta module name
#   meta command name {shape} ? { clause ... } ?
#   meta command name variants {
#       form {shape} ? { clause ... } ?
#       command name {shape} ? { clause ... } ?
#       command name variants { ... }
#   }
#   meta language languageName {
#       command name {shape} ? { clause ... } ?
#       command name variants {
#           form {shape} ? { clause ... } ?
#           command name {shape} ? { clause ... } ?
#           command name variants { ... }
#       }
#   }
#
# `name` is a single command word. Nested command words must be declared with
# `command`.
#
# `shape` is the structural form of one callable command shape. It is not
# display-only text. Single-form commands may elide `form`; commands that use
# explicit `form` entries should use `variants`.
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
# command name {signature} ? { annotation ... } ?
# command name variants { ... }
#   Declare a nested command using the same shape as `meta command`. The
#   declared name also contributes to the parent's command tree.
#
# bind selector ?kind?
#   Treat the selected argument as the name of a variable binding introduced by
#   this command. `kind` is optional when it can be inferred from the command
#   name tail; otherwise it should be explicit.
#
# ref selector
#   Treat the selected argument as the name of a variable reference.
#
# enter language body selector ? owner selector ?
#   Enter the named embedded command language for the selected body argument or
#   arguments. `owner` is optional. Use `enter tcl body ...` for Tcl bodies.
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
#       params select selector | literal {name ...} | -
#       body select selector
#       language name
#       _params-source select selector
#
# plugin script commandPrefix
#   Run a Tcl plugin to produce dynamic metadata effects. Plugin procedure
#   effects should use the same `select`/`literal` field vocabulary as the
#   declarative `procedure` annotation.
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
    command module {name}

    # Declare metadata for a command or command prefix.
    # Use `meta command name {shape}` for single-form commands, or
    # `meta command name variants { ... }` for explicit `form` and nested
    # `command` declarations.
    command command variants {
        form {name shape}
        form {name shape body}
        form {name variants body}
    }

    # Declare an embedded command language and the commands valid within it.
    # The body contains `command name {shape}` or
    # `command name variants { ... }` entries that are only valid while a
    # matching `enter` clause is active.
    command language {name body}
}
