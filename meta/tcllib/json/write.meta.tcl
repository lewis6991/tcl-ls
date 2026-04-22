# Json::write package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module json::write

# Generate JSON output using the json::write ensemble.
meta command json::write {subcommand args} {
    # Get or set pretty-print indentation.
    command indented {?bool?}

    # Get or set key alignment for object output.
    command aligned {?bool?}

    # Quote a plain Tcl string as JSON.
    command string {text}

    # Build a JSON array from preformatted JSON values.
    command array {args}

    # Build a JSON array from plain Tcl strings.
    command array-strings {args}

    # Build a JSON object from key/value pairs.
    command object {args}

    # Build a JSON object from plain string values.
    command object-strings {args}
}
