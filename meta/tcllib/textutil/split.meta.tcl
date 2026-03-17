# Textutil::split package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module textutil::split

# Split a string into fixed-width chunks.
meta command textutil::split::splitn {text {?len?}}

# Split a string on a regular expression.
meta command textutil::split::splitx {text {?regexp?}}
