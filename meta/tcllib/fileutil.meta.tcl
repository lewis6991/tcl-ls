# Fileutil package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module fileutil

# Read and concatenate the contents of one or more files.
meta command fileutil::cat {args}

# Search a directory tree for files matching glob or regexp patterns.
meta command fileutil::findByPattern {basedir args}

# Remove a fixed number of leading path elements.
meta command fileutil::stripN {path n}

# Make a path relative to a prefix when possible.
meta command fileutil::stripPath {prefix path}

# Split file-writing options from output variable names.
# Stores the parsed option list, filename, and trailing named outputs in the
# caller variables passed by name.
meta command fileutil::Spec {check alist ov fv args} {
    bind 3 set
    bind 4 set
    bind 5.. set
}

# Write data to a file with optional encoding and translation control.
meta command fileutil::writeFile {args}

# Create a temporary file and return its pathname.
meta command fileutil::tempfile {?prefix?}
