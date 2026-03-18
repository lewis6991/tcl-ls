# Json package command metadata for tcl-ls.
# This file is parsed as Tcl source so docs live in leading comments.
meta module json

# Parse a JSON document into a Tcl dict/list structure.
meta command json::json2dict {jsonText}

# Parse multiple JSON documents from one string.
meta command json::many-json2dict {jsonText ? max ?}
