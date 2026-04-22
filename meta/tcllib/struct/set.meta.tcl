# Struct::set package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module struct::set

# Manipulate finite sets through the struct::set ensemble.
meta command struct::set {subcommand args} {
    # Test whether a set is empty.
    command empty {setValue}

    # Return the cardinality of a set.
    command size {setValue}

    # Test whether an item is a member of a set.
    command contains {setValue item}

    # Compute the union of one or more sets.
    command union {args}

    # Compute the intersection of one or more sets.
    command intersect {args}

    # Compute setA - setB.
    command difference {setA setB}

    # Compute the symmetric difference of two sets.
    command symdiff {setA setB}

    # Return the intersection and pairwise differences of two sets.
    command intersect3 {setA setB}

    # Test whether two sets are equal.
    command equal {setA setB}

    # Add an item to the named set variable.
    command include {setVar item} {
        bind 1 set
    }

    # Remove an item from the named set variable.
    command exclude {setVar item} {
        bind 1 set
    }

    # Add all elements of a set to the named set variable.
    command add {setVar setValue} {
        bind 1 set
    }

    # Remove all elements of a set from the named set variable.
    command subtract {setVar setValue} {
        bind 1 set
    }

    # Test whether one set is a subset of another.
    command subsetof {setA setB}
}
