# Clay package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Define a clay class or object with a declarative body script.
meta command clay::define {target body}

# Merge nested dictionary trees into the named variable.
meta command clay::tree::dictmerge {varname args}

# Merge dictionary tree values and return the combined result.
meta command clay::tree::merge {args}
