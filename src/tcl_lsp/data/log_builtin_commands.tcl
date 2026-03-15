# Log package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Log a message at the specified log level.
meta command log::log {level text}

# Log a message at info level.
meta command log::info {text}

# Log a message at debug level.
meta command log::debug {text}
