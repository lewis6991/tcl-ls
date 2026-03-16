# Tepam package command metadata for tcl-ls.
meta module tepam

# Declare a procedure using Tepam's attribute DSL.
meta command tepam::procedure {name attributes body} {
    plugin tepam.tm ::tcl_lsp::plugins::tepam::statementWords
}
