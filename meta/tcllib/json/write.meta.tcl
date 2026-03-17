# Json::write package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module json::write

# Generate JSON output using the json::write ensemble.
meta command json::write {subcommand args} {
    # Get or set pretty-print indentation.
    subcommand indented {?bool?}

    # Get or set key alignment for object output.
    subcommand aligned {?bool?}

    # Quote a plain Tcl string as JSON.
    subcommand string {text}

    # Build a JSON array from preformatted JSON values.
    subcommand array {args}

    # Build a JSON array from plain Tcl strings.
    subcommand array-strings {args}

    # Build a JSON object from key/value pairs.
    subcommand object {args}

    # Build a JSON object from plain string values.
    subcommand object-strings {args}
}
