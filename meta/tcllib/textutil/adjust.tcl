# Textutil::adjust package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Reflow a paragraph of text.
meta command textutil::adjust::adjust {text args} {
    option -full value
    option -hyphenate value
    option -justify value
    option -length value
    option -strictlength value
}

# Return the path to a bundled hyphenation pattern file.
meta command textutil::adjust::getPredefined {name}

# Indent each line in a block of text.
meta command textutil::adjust::indent {text prefix {?skip?}}

# List the bundled hyphenation pattern files.
meta command textutil::adjust::listPredefined {}

# Load hyphenation patterns from a file.
meta command textutil::adjust::readPatterns {filename}

# Remove common leading indentation from a block of text.
meta command textutil::adjust::undent {text}
