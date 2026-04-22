# TclOO package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module TclOO

# Create or introspect Tcl classes via the TclOO class ensemble.
meta command oo::class {subcommand args} {
    # Create a new TclOO class, optionally evaluating a definition script.
    command create {className ?definitionScript?} {
        enter tcloo-definition body 2 owner 1
    }
}

# Define or introspect a class using TclOO keywords and scripts.
meta command oo::define {className args} {
    enter tcloo-definition body 2.. owner 1
}

# Define or introspect an object using TclOO keywords and scripts.
meta command oo::objdefine {objectName args} {
    enter tcloo-definition body 2.. owner 1
}

meta language tcloo-definition {
    command method {name args body} {
        procedure {
            name select 1
            params select 2
            body select 3
            language tcloo-method
        }
    }

    command constructor {args body} {
        procedure {
            name -
            params select 1
            body select 2
            language tcloo-method
        }
    }

    command destructor {body} {
        procedure {
            name -
            params -
            body select 1
            language tcloo-method
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

meta language tcloo-method {
    command my {methodName args} {
        command variable {name args} {
            bind 1.. variable
            ref 1..
        }
    }

    command next {args}
    command self {args}
}
