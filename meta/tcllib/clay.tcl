# Clay package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Define a Clay class or object with a declarative body script.
meta command clay::define {target body} {
    context clay-definition {
        body 2
        owner 1
    }
}

# Create a Clay class, optionally evaluating a definition script.
meta command clay::class {subcommand args} {
    # Create a Clay class and optionally run a definition body.
    subcommand create {className ?definitionScript?} {
        context clay-definition {
            body 2
            owner 1
        }
    }
}

# Merge nested dictionary trees into the named variable.
meta command clay::tree::dictmerge {varname args}

# Merge dictionary tree values and return the combined result.
meta command clay::tree::merge {args}

meta context clay-definition {
    # Clay inherits the standard TclOO definition commands.
    command method {name args body}
    command constructor {args body}
    command destructor {body}

    command deletemethod {name}
    command export {name args}
    command filter {args}
    command forward {name commandPrefix args}
    command mixin {args}
    command renamemethod {from to}
    command superclass {args}
    command unexport {name args}
    command variable {name args}

    # Clay adds its own definition keywords on top of TclOO.
    command Array {name ?values?}
    command Delegate {name info}
    command Dict {name ?values?}
    command Option {name args}
    command Option_Class {name args}
    command Variable {name ?default?}

    command Class_Method {name arglist body}
    command class_method {name arglist body}
    command Ensemble {rawmethod argspec body}

    command clay {args}
    command aliases {args}
    command current_class {}
}
