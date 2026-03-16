# Tepam package command metadata for tcl-ls.

# Declare a procedure using Tepam's attribute DSL.
meta command tepam::procedure {name attributes body} {
    plugin tepam.tm ::tcl_lsp::plugins::tepam::statementWords
}
