# TclOO package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Create or introspect Tcl classes via the TclOO class ensemble.
meta command oo::class {subcommand args} {
    # Create a new TclOO class, optionally evaluating a definition script.
    subcommand create {className ?definitionScript?} {
        context tcloo-definition {
            body 2
            owner 1
        }
    }
}

# Define or introspect a class using TclOO keywords and scripts.
meta command oo::define {className args} {
    context tcloo-definition {
        body 2..
        owner 1
    }
}

# Define or introspect an object using TclOO keywords and scripts.
meta command oo::objdefine {objectName args} {
    context tcloo-definition {
        body 2..
        owner 1
    }
}

meta context tcloo-definition {
    command method {name args body} {
        procedure {
            name 1
            params 2
            body 3
            context tcloo-method
        }
    }

    command constructor {args body} {
        procedure {
            name -
            params 1
            body 2
            context tcloo-method
        }
    }

    command destructor {body} {
        procedure {
            name -
            params -
            body 1
            context tcloo-method
        }
    }

    command deletemethod {name}
    command export {name args}
    command filter {args}
    command forward {name commandPrefix args}
    command mixin {args}
    command renamemethod {from to}
    command superclass {args}
    command unexport {name args}
    command variable {name args}
}

meta context tcloo-method {
    command my {methodName args} {
        subcommand variable {name args} {
            bind 1.. variable
            ref 1..
        }
    }

    command next {args}
    command self {args}
}
