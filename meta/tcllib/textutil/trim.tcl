# Textutil::trim package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Trim a regular expression from both sides of a string.
meta command textutil::trim::trim {text {?regexp?}}

# Remove an empty heading from a text block.
meta command textutil::trim::trimEmptyHeading {text}

# Remove a fixed prefix from a string.
meta command textutil::trim::trimPrefix {text prefix}

# Trim a regular expression from the left side of a string.
meta command textutil::trim::trimleft {text {?regexp?}}

# Trim a regular expression from the right side of a string.
meta command textutil::trim::trimright {text {?regexp?}}
