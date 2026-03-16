# Struct::set package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Manipulate finite sets through the struct::set ensemble.
meta command struct::set {subcommand args} {
    # Test whether a set is empty.
    subcommand empty {setValue}

    # Return the cardinality of a set.
    subcommand size {setValue}

    # Test whether an item is a member of a set.
    subcommand contains {setValue item}

    # Compute the union of one or more sets.
    subcommand union {args}

    # Compute the intersection of one or more sets.
    subcommand intersect {args}

    # Compute setA - setB.
    subcommand difference {setA setB}

    # Compute the symmetric difference of two sets.
    subcommand symdiff {setA setB}

    # Return the intersection and pairwise differences of two sets.
    subcommand intersect3 {setA setB}

    # Test whether two sets are equal.
    subcommand equal {setA setB}

    # Add an item to the named set variable.
    subcommand include {setVar item} {
        bind 1 set
    }

    # Remove an item from the named set variable.
    subcommand exclude {setVar item} {
        bind 1 set
    }

    # Add all elements of a set to the named set variable.
    subcommand add {setVar setValue} {
        bind 1 set
    }

    # Remove all elements of a set from the named set variable.
    subcommand subtract {setVar setValue} {
        bind 1 set
    }

    # Test whether one set is a subset of another.
    subcommand subsetof {setA setB}
}
