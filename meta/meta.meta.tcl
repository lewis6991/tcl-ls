# Metadata command format for tcl-ls.
#
# Metadata files use the `meta` ensemble for structured declarations and
# conventionally use the `.meta.tcl` suffix. Annotation bodies remain data.
#
# Hover help is defined beside each schema command below.
# Literal `?` words only appear inside `shape` lists.
meta module Tcl {
    # Describe Tcl commands for static analysis. Annotation bodies are data.
    #
    # Syntax: a subcommand followed by positional arguments and braced blocks.
    #
    # **Declarations**
    #
    # - `module`: group declarations under a metadata module.
    # - `command`: describe a command's arguments and analysis behavior.
    # - `language`: describe commands allowed in an embedded script.
    # - `alias`: reuse another command's metadata.
    # - `override`: replace a command from Tcl or a lower module.
    # - `source`: record a fixed dependency of the associated Tcl file.
    #
    # Hover over a subcommand or annotation for its options and an example.
    # Use ordinary `source path` to include metadata files.
    #
    # **Example**
    #
    # ```tcl
    # meta module Tcl {
    #     meta command run {script} {
    #         enter tcl body 1
    #     }
    # }
    # ```
    meta command meta {subcommand args} {
        # Syntax: a module name followed by a braced command block.
        #
        # Group declarations under this module. Included files inherit the module.
        # Nested modules restore the outer module when their blocks end.
        # `Tcl` and `TclOO` are active by default. Other modules need a package
        # requirement, a source directive, or a project rule.
        #
        # **Example**
        #
        # ```tcl
        # meta module Tcl {meta command tool::run {script}}
        # ```
        command module {<name> <body>} {enter tcl body last}

        # Syntax: one positional path.
        #
        # Record a fixed dependency of the associated Tcl file.
        # In `tcllsrc.tcl`, the dependency applies to all covered source files.
        # The path is relative to this metadata file.
        # Allowed only outside module blocks. Use ordinary `source path` to
        # include metadata declarations instead.
        #
        # **Example**
        #
        # ```tcl
        # meta source ../src/common.tcl
        # ```
        command source {<path>}

        # Syntax: two positional names, with optional `-module moduleName`.
        #
        # Reuse the target's shapes, annotations, documentation, and subcommands.
        # Requires a module block. The alias leaves the target metadata in place.
        #
        # **Options**
        #
        # - `-module moduleName`: select the target's module.
        #   Default: the enclosing module. Missing targets and cycles are errors.
        #
        # **Example**
        #
        # ```tcl
        # meta alias tcl_clock clock -module Tcl
        # ```
        command alias variants {
            form {<name> <target>}
            form {<name> <target> =-module <moduleName>}
        }

        # Syntax: a name followed by a braced shape or a `variants` block.
        #
        # Replace a command from Tcl or a lower active module.
        # Requires a module block. Accepts the same shapes and annotations
        # as `command`, including a `variants` block with one or more `form` entries.
        #
        # **Options**
        #
        # - `-visibility public|internal`: place before the shape or `variants`.
        #   Default: `public`.
        #
        # **Example**
        #
        # ```tcl
        # meta override clock {args}
        # ```
        command override variants {
            form {<name> <shape>}
            form {<name> <groupedShape> <body>} {enter meta-command-body body last}
            form {<name> =variants <body>} {enter meta-command-body body last}
            form {<name> =-visibility <visibility> <shape>}
            form {<name> =-visibility <visibility> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> =variants <body>} {
                enter meta-command-body body last
            }
        }

        # Syntax: a name followed by a braced shape or a `variants` block.
        #
        # Describe a command's arguments and analysis behavior.
        # The name is one word, optionally namespace-qualified.
        # Use nested `command` declarations for subcommands.
        #
        # **Forms**
        #
        # - `meta command name {shape}`: describe one callable form.
        # - `meta command name {shape} {annotations}`: add analysis behavior.
        # - `meta command name variants {forms}`: declare several callable forms.
        #   The block must contain at least one `form` for its own command.
        #
        # **Options**
        #
        # - `-visibility public|internal`: place before the shape or `variants`.
        #   Default: `public`. Each nested command has its own visibility.
        #
        # **Shape items**
        #
        # - `name`: one argument; `args`: the remaining arguments.
        # - `? value ?` or `{name default}`: an optional argument.
        # - `=word`: a required literal word.
        #
        # **Example**
        #
        # ```tcl
        # meta command run {script} {enter tcl body 1}
        # ```
        command command variants {
            form {<name> <shape>}
            form {<name> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =variants <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> <shape>}
            form {<name> =-visibility <visibility> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> =variants <body>} {
                enter meta-command-body body last
            }
        }

        # Syntax: a language name followed by a braced command block.
        #
        # Define the commands valid in an embedded script. The name is one word.
        # `enter` or a procedure's `language` field selects this language.
        #
        # **Body commands**
        #
        # - `command`: describe an embedded command.
        # - `override`: replace an embedded command from a lower module.
        # - `extends tcl`: also allow ordinary Tcl commands.
        #   Default: closed; only declared commands are valid.
        #
        # **Example**
        #
        # ```tcl
        # meta language tool-script {extends tcl; command prove {property}}
        # ```
        command language {<name> <body>} {
            enter meta-language-body body 2
        }
    }

    meta language meta-command-body {
        # Syntax: positional arguments. `value` and `stop` are literal words.
        #
        # **Forms**
        #
        # - `option name`: declare a flag without a value.
        # - `option name value`: consume one value after the option.
        # - `option -- stop`: make `--` end option parsing.
        #
        # Use these options with `after-options` selectors.
        #
        # **Example**
        #
        # ```tcl
        # option -start value
        # ```
        command option variants {
            form {<name>}
            form {<name> =value}
            form {=-- =stop}
        }

        # Syntax: a name followed by a braced shape or a `variants` block.
        #
        # Describe a subcommand of the enclosing command.
        # The name is one word, optionally namespace-qualified.
        # Use nested `command` declarations for subcommands.
        #
        # **Forms**
        #
        # - `command name {shape}`: describe one callable form.
        # - `command name {shape} {annotations}`: add analysis behavior.
        # - `command name variants {forms}`: declare several callable forms.
        #   The block must contain at least one `form` for its own command.
        #
        # **Options**
        #
        # - `-visibility public|internal`: place before the shape or `variants`.
        #   Default: `public`. Each nested command has its own visibility.
        #
        # **Shape items**
        #
        # - `name`: one argument; `args`: the remaining arguments.
        # - `? value ?` or `{name default}`: an optional argument.
        # - `=word`: a required literal word.
        #
        # **Example**
        #
        # ```tcl
        # command run {script} {enter tcl body 1}
        # ```
        command command variants {
            form {<name> <shape>}
            form {<name> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =variants <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> <shape>}
            form {<name> =-visibility <visibility> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> =variants <body>} {
                enter meta-command-body body last
            }
        }

        # Syntax: a braced shape followed by an optional annotation block.
        #
        # Declare one callable form inside a `variants` block.
        # Plain shape words describe arguments. `=word` matches a literal word.
        # `? value ?` and `{name default}` describe optional arguments.
        # `args` consumes the remaining arguments and must be last.
        #
        # **Example**
        #
        # ```tcl
        # form {filename mode channel body} {bind 3 set; enter tcl body 4}
        # ```
        command form variants {
            form {<shape>}
            form {<groupedShape> <body>} {
                enter meta-command-body body 2
            }
        }

        # Syntax: positional arguments.
        #
        # Record variable bindings selected from runtime arguments.
        # Selectors start at 1 after the matched command prefix.
        #
        # **Selector forms**
        #
        # - `1`, `last`, `last-1`: one argument.
        # - `2..`, `2..4`: an argument range; add `step N` for a positive stride.
        # - `list 2`: variable names from a Tcl list.
        # - `after-options 2`: a position after declared options and their values.
        #
        # **Binding kinds**
        #
        # `append`, `array`, `catch`, `foreach`, `gets`, `global`, `incr`,
        # `lappend`, `lassign`, `lmap`, `parameter`, `regexp`, `regsub`,
        # `scan`, `set`, `switch`, `upvar`, `variable`.
        #
        # Omit the kind only if the enclosing command name tail is a binding kind.
        #
        # **Example**
        #
        # ```tcl
        # bind 3 set
        # ```
        command bind variants {
            form {<selector>}
            form {<selector> <kind>}
        }

        # Syntax: positional arguments.
        #
        # Record references to variable names selected from runtime arguments.
        # Selectors start at 1 after the matched command prefix.
        # Use `ref selector` for a plain reference. An optional braced block
        # contains `if-missing {hint message}` or `if-missing {information message}`.
        # The check uses the state before the command runs. Declare creation
        # separately with `bind`; the check does not change plain references.
        #
        # **Selector forms**
        #
        # - `1`, `last`, `last-1`: one argument.
        # - `2..`, `2..4`: a range; add `step N` for a positive stride.
        # - `list 2`: variable names from a Tcl list.
        # - `after-options 2`: a position after declared options and their values.
        #
        # **Example**
        #
        # ```tcl
        # ref 3
        # ref 1 {if-missing {hint "Variable is first created here."}}
        # ```
        command ref variants {
            form {<selector>}
            form {<selector> <body>} {
                enter meta-ref-body body last
            }
        }

        # Syntax: a selector, optionally followed by `namespace` and an absolute name.
        #
        # Describe a forwarded command invocation. The first selected word is
        # the command name; the remaining words are its arguments.
        # Selectors start at 1 after the matched command prefix.
        # Words keep their argument boundaries and are not parsed as a script.
        # Substitutions belong to the caller.
        #
        # **Options**
        #
        # - `namespace absoluteName`: resolve the command in this namespace.
        #   Use `::` for the root namespace. Default: the caller's namespace.
        #
        # A selector must choose contiguous words. `after-options` is allowed;
        # `list` and non-contiguous steps are not.
        # Hover, navigation, completion, signature help, and semantic tokens
        # use the selected command's definition. This does not execute the call
        # or analyze arguments as nested script bodies.
        #
        # **Example**
        #
        # ```tcl
        # call 1.. namespace ::
        # ```
        command call {<selector> ? =namespace <absoluteName> ?}

        # Syntax: positional arguments. `body` and `owner` are literal words.
        #
        # Parse selected runtime arguments in the named embedded language.
        # Selectors start at 1 after the matched command prefix.
        #
        # **Arguments**
        #
        # - `language`: `tcl` or a language declared with `meta language`.
        # - `body selector`: one argument or a contiguous argument range.
        #   `after-options` is allowed; `list` and non-contiguous steps are not.
        # - `owner selector`: optional owning entity, read from one argument.
        #   `list` and `after-options` are not allowed.
        #
        # One body word is a script. A range forms an inline command stream.
        # Structured Tcl commands allow only their existing single-word bodies.
        # Overlapping body selections are errors.
        #
        # **Example**
        #
        # ```tcl
        # enter tcl body 4
        # enter tool-script body 2.. owner 1
        # ```
        command enter variants {
            form {<language> =body <bodySelector>}
            form {<language> =body <bodySelector> =owner <ownerSelector>}
        }

        # Syntax: positional arguments.
        #
        # Record source-file dependencies selected from runtime arguments.
        # Selectors start at 1 after the matched command prefix.
        #
        # **Bases (choose one)**
        #
        # - `caller`: relative to the file containing the call.
        # - `definition`: the parent of the directory containing the helper's Tcl file.
        #
        # Each selected argument is one path. Plugin effects also support list
        # selectors; their `definition` base is the metadata file's directory.
        #
        # **Example**
        #
        # ```tcl
        # source 1 caller
        # ```
        command source variants {
            form {<selector> =caller}
            form {<selector> =definition}
        }

        # Syntax: key/value list.
        #
        # **Source (choose one)**
        #
        # - `select selector`: read the package name from one runtime argument.
        # - `literal packageName`: use a fixed package name.
        #
        # Empty settings and list selectors are not allowed.
        # Group a selector containing several words, such as `{after-options 1}`.
        # Duplicate and unknown keys are errors.
        #
        # **Example**
        #
        # ```tcl
        # package {literal TclOO}
        # ```
        command package {<packageSettings>}

        # Syntax: a braced command block.
        #
        # Describe a procedure declaration made by the enclosing command.
        # Each source field takes a braced key/value list.
        #
        # **Fields**
        #
        # - `name`: required; the declared name.
        # - `params`: required; the parameter definitions.
        # - `body`: optional; the script body.
        # - `language`: optional; the body's embedded language (default: `tcl`).
        #   Requires `body`.
        #
        # Each field may appear once. Hover over a field for its supported keys.
        #
        # **Example**
        #
        # ```tcl
        # procedure {
        #     name {select 1}
        #     params {select 2}
        #     body {select 3}
        # }
        # ```
        command procedure {<body>} {
            enter meta-procedure-body body 1
        }

        # Syntax: two positional values.
        #
        # Call a Tcl hook to produce dynamic metadata for each matching command.
        #
        # **Arguments**
        #
        # - `script`: path relative to this metadata file; must exist when loaded.
        # - `procName`: the hook, invoked as `procName words info`.
        #   `words` is the full source command; `info` is a Tcl dictionary.
        #
        # Return a Tcl list of `bind`, `ref`, `call`, `enter`, `package`, `source`, or
        # `procedure` effects. Procedure fields use the same braced settings.
        # Use `::tcl_lsp::word index` or `::tcl_lsp::variable name` for known values.
        # `::tcl_lsp::source_list_items value` and `::tcl_lsp::slice value start end`
        # preserve source locations. Return their IDs as `params {items {id ...}}`.
        # These items bind body variables and leave call argument counts unknown.
        # Unknown values are empty; the host does not execute project Tcl.
        # Plugin selectors count from 1 including the command name and subcommands.
        # `after-options` is not supported. The host requires `tclsh` on `PATH`.
        #
        # **Example**
        #
        # ```tcl
        # plugin declare.tcl ::project::metadata::declare
        # ```
        command plugin {<script> <procName>}
    }

    meta language meta-language-body {
        # Syntax: one positional literal, `tcl`.
        #
        # Allow ordinary Tcl commands after checking this language's declarations.
        # `tcl` is the only supported base language. Declare it at most once.
        # Default: closed; only declared commands are valid.
        #
        # **Example**
        #
        # ```tcl
        # extends tcl
        # ```
        command extends {=tcl}

        # Syntax: a name followed by a braced shape or a `variants` block.
        #
        # Replace a command from a lower module in this embedded language.
        # Requires a module block. Accepts the same shapes and annotations
        # as `command`, including a `variants` block with one or more `form` entries.
        #
        # **Options**
        #
        # - `-visibility public|internal`: place before the shape or `variants`.
        #   Default: `public`.
        #
        # **Example**
        #
        # ```tcl
        # override clock {args}
        # ```
        command override variants {
            form {<name> <shape>}
            form {<name> <groupedShape> <body>} {enter meta-command-body body last}
            form {<name> =variants <body>} {enter meta-command-body body last}
            form {<name> =-visibility <visibility> <shape>}
            form {<name> =-visibility <visibility> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> =variants <body>} {
                enter meta-command-body body last
            }
        }

        # Syntax: a name followed by a braced shape or a `variants` block.
        #
        # Describe a command available in this embedded language.
        # The name is one word, optionally namespace-qualified.
        # Use nested `command` declarations for subcommands.
        #
        # **Forms**
        #
        # - `command name {shape}`: describe one callable form.
        # - `command name {shape} {annotations}`: add analysis behavior.
        # - `command name variants {forms}`: declare several callable forms.
        #   The block must contain at least one `form` for its own command.
        #
        # **Options**
        #
        # - `-visibility public|internal`: place before the shape or `variants`.
        #   Default: `public`. Each nested command has its own visibility.
        #
        # **Shape items**
        #
        # - `name`: one argument; `args`: the remaining arguments.
        # - `? value ?` or `{name default}`: an optional argument.
        # - `=word`: a required literal word.
        #
        # **Example**
        #
        # ```tcl
        # command run {script} {enter tcl body 1}
        # ```
        command command variants {
            form {<name> <shape>}
            form {<name> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =variants <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> <shape>}
            form {<name> =-visibility <visibility> <groupedShape> <body>} {
                enter meta-command-body body last
            }
            form {<name> =-visibility <visibility> =variants <body>} {
                enter meta-command-body body last
            }
        }
    }

    meta language meta-ref-body {
        # Check whether the selected variable is missing before the command runs.
        # The body contains one hint or information action with a static message.
        command if-missing {<body>} {
            enter meta-if-missing-body body 1
        }
    }

    meta language meta-if-missing-body {
        # Report a hint when the referenced variable is known to be missing.
        command hint {message}
        # Report information when the referenced variable is known to be missing.
        command information {message}
    }

    meta language meta-procedure-body {
        # Syntax: key/value list.
        #
        # **Source (choose one)**
        #
        # - `select selector`: read the name from one runtime argument.
        # - `literal name`: use a fixed declared name.
        #
        # `name {}` uses the enclosing command name tail.
        # Selectors start at 1 after the matched command prefix.
        # List selectors and ranges selecting several arguments are not allowed.
        # Group a selector containing several words, such as `{after-options 1}`.
        # Duplicate and unknown keys are errors.
        #
        # **Example**
        #
        # ```tcl
        # name {select 1}
        # ```
        command name {<nameSettings>}

        # Syntax: key/value list.
        #
        # **Source (choose one)**
        #
        # - `select selector`: read one runtime argument.
        # - `literal parameterList`: use a fixed Tcl parameter list.
        #
        # Use `params {}` for no parameters.
        # Duplicate and unknown keys are errors.
        # Lists use Tcl procedure syntax: names, `{name default}`, and trailing `args`.
        # A known literal variable can supply the selected parameter list.
        # Use a Tcl plugin for other parameter syntaxes.
        #
        # **Optional parser**
        #
        # - `plugin {script procName}`: parse the selected source value.
        #   Requires `select`; the script path is relative to this metadata file.
        #   The hook is called as `procName value info`.
        #   `value` has `id`, `text`, and `grouped`; `info` is the call context.
        #   Return `items {sourceId ...}`, or `{}` when the input is unknown.
        #   `items {}` declares no parameters. Call argument counts stay unknown.
        #
        # The language server does not execute project Tcl or evaluate defaults.
        #
        # **Example**
        #
        # ```tcl
        # params {select 2}
        # params {select 2 plugin {header.tcl ::project::metadata::parameters}}
        # ```
        command params {<parameterSettings>}

        # Syntax: key/value list.
        #
        # **Supported key**
        #
        # - `select selector`: choose one runtime argument as the script body.
        #
        # Selectors start at 1 after the matched command prefix.
        # Group a selector containing several words, such as `{after-options 3}`.
        # Literal sources, empty settings, and list selectors are not allowed.
        # Omit this field for a declaration without a body.
        #
        # **Example**
        #
        # ```tcl
        # body {select 3}
        # ```
        command body {<bodySettings>}

        # Syntax: one positional value.
        #
        # Select the embedded language for the declared procedure's body.
        # Use `tcl` or a language declared with `meta language`.
        # Requires a `body` field. Default: `tcl`.
        #
        # **Example**
        #
        # ```tcl
        # language tcloo-method
        # ```
        command language {<name>}
    }
}

# Selected automatically when editing a .meta.tcl declaration file.
meta module TclLSMetadata {
    # Syntax: one positional path.
    #
    # Include static metadata declarations at this point.
    # Relative paths start in this metadata file's directory.
    # Included files inherit the enclosing module, if present.
    # Direct metadata loading requires a static path. Files sourced from an rc
    # script run as Tcl and can use substitutions. Missing files and include
    # cycles are errors.
    #
    # **Example**
    #
    # ```tcl
    # source common.meta.tcl
    # ```
    meta override source {<path>}
}
