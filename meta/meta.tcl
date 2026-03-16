# Metadata command format for tcl-ls.
#
# Metadata files use the `meta` ensemble for structured declarations instead of
# executable behavior.
#
# Top-level declarations:
#   meta command name {signature} ? { annotation ... } ?
#   meta context contextName {
#       command name {signature} ? { annotation ... } ?
#   }
#
# `name` is a single command word. Nested command words must be declared with
# `subcommand`.
#
# Signatures use Tcl command syntax with optional arguments written literally.
#
# Annotation bodies:
#   annotationBody is a static Tcl command list, usually written as a braced
#   block. Each nested command in the block is one annotation.
#
#   Example:
#       meta command regexp {args} {
#           option -all
#           option -start value
#           option -- stop
#           bind after-options 3..
#       }
#
# Selector syntax:
#   Selectors point at arguments in the declared signature using positive
#   1-based positions.
#
#   1       the first argument
#   3..     the third argument through the end
#   list 2  split argument 2 as a Tcl list and select each item
#   after-options 2
#           resolve the second positional argument after known options
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
# subcommand name {signature} ? { annotation ... } ?
#   Declare a subcommand using the same shape as `meta command`. The declared
#   name also contributes to the parent's subcommand set.
#
# bind selector ?kind?
#   Treat the selected argument as the name of a variable binding introduced by
#   this command. `kind` is optional when it can be inferred from the command
#   name tail; otherwise it should be explicit.
#
# ref selector
#   Treat the selected argument as the name of a variable reference.
#
# script-body selector
#   Treat the selected argument as an embedded Tcl script and analyze it.
#
# source selector call-source-directory|proc-source-parent
#   Treat the selected argument as a source path. The final token picks the
#   base directory used to resolve that path.
#
# package name|selector
#   Record a package dependency. Use a literal package name for fixed
#   dependencies or a selector when the package name comes from an argument.
#
# context context-name {
#     body selector
#     owner selector
# }
#   Enter the named embedded command language for the selected body argument or
#   arguments. `owner` names the entity that owns the context instance, which
#   lets nested procedure-like declarations get stable qualified names and a
#   namespace anchor.
#
# procedure {
#     name index|-
#     params index|-
#     body index
#     context body-context
# }
#   Describe a procedure-like command declaration. `name` selects the declared
#   member name, or `-` when the command has no separate member name. `params`
#   selects the formal Tcl argument list, or `-` when there is none.
#   `body` selects the script body. `context` is optional and sets the embedded
#   language used when analyzing that body.
#
# plugin scriptPath procName
#   Invoke a Tcl plugin hook for matching command instances. `scriptPath` is
#   resolved relative to the metadata file that declares it. The plugin proc is
#   called as `procName words info`, where `words` is the command words as
#   static strings when available and `info` is a dict with context like
#   `metadata-command`, `namespace`, `prefix-word-count`, `static-flags`, and
#   `expanded-flags`.
#
#   Plugins run inside a fresh safe Tcl interpreter for each call. They do not
#   share state with other plugin invocations, and file, package, interpreter,
#   and channel commands are not available there.
#
#   The proc returns a Tcl list of effects. The supported effect format is:
#       procedure {
#           name-index N
#           params-word-index N
#           params {name ...}
#           body-index N
#           context body-context
#       }
#
# A command can use multiple annotations in one body when needed.
#
# Declare metadata for Tcl language entities.
# Tcl-ls treats this as structured documentation instead of executable
# behavior. `meta` is an ensemble whose subcommands describe command metadata
# and embedded command contexts.
meta command meta {subcommand args} {
    # Declare metadata for a command or command prefix.
    # Use `meta command name {signature}` for plain declarations, or add an
    # annotation body to describe options, bindings, nested script bodies,
    # package loading, or embedded command contexts.
    subcommand command {name signature ? annotationBody ?}

    # Declare an embedded command language and the commands valid within it.
    # The body contains `command name {signature}` entries that are only valid
    # while a matching `context` annotation is active.
    subcommand context {name body}
}
