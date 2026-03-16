# Textutil::tabify package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module textutil::tabify

# Convert runs of spaces to tabs.
meta command textutil::tabify::tabify {text {?tabWidth?}}

# Alternate tabify implementation with tab stop control.
meta command textutil::tabify::tabify2 {text {?tabWidth?}}

# Expand tabs into spaces.
meta command textutil::tabify::untabify {text {?tabWidth?}}

# Alternate untabify implementation with tab stop control.
meta command textutil::tabify::untabify2 {text {?tabWidth?}}
