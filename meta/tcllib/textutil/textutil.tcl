# Textutil bundle command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Reflow a paragraph of text.
meta command textutil::adjust {text args} {
    option -full value
    option -hyphenate value
    option -justify value
    option -length value
    option -strictlength value
}

# Indent each line in a block of text.
meta command textutil::indent {text prefix {?skip?}}

# Remove common leading indentation from a block of text.
meta command textutil::undent {text}

# Remove the first character from a string.
meta command textutil::chop {text}

# Remove the last character from a string.
meta command textutil::tail {text}

# Uppercase the first character of a string.
meta command textutil::cap {text}

# Lowercase the first character of a string.
meta command textutil::uncap {text}

# Uppercase the first character of each word.
meta command textutil::capEachWord {sentence}

# Compute the longest common prefix of one or more strings.
meta command textutil::longestCommonPrefix {args}

# Compute the longest common prefix of a list of strings.
meta command textutil::longestCommonPrefixList {items}

# Repeat a string a fixed number of times.
meta command textutil::strRepeat {text count}

# Return a string of blank characters.
meta command textutil::blank {count}

# Split a string on a regular expression.
meta command textutil::splitx {text {?regexp?}}

# Split a string into fixed-width chunks.
meta command textutil::splitn {text {?len?}}

# Trim a regular expression from both sides of a string.
meta command textutil::trim {text {?regexp?}}

# Trim a regular expression from the left side of a string.
meta command textutil::trimleft {text {?regexp?}}

# Trim a regular expression from the right side of a string.
meta command textutil::trimright {text {?regexp?}}

# Remove a fixed prefix from a string.
meta command textutil::trimPrefix {text prefix}

# Remove an empty heading from a text block.
meta command textutil::trimEmptyHeading {text}

# Convert runs of spaces to tabs.
meta command textutil::tabify {text {?tabWidth?}}

# Expand tabs into spaces.
meta command textutil::untabify {text {?tabWidth?}}

# Alternate tabify implementation with tab stop control.
meta command textutil::tabify2 {text {?tabWidth?}}

# Alternate untabify implementation with tab stop control.
meta command textutil::untabify2 {text {?tabWidth?}}
