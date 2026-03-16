# Textutil::wcswidth package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.

# Return the East Asian width class for a character codepoint.
meta command textutil::wcswidth_type {codepoint}

# Return the display width of a single character codepoint.
meta command textutil::wcswidth_char {codepoint}

# Return the display width of a string.
meta command textutil::wcswidth {text}
