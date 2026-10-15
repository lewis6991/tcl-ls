LSP Features
============

``tcl-ls`` uses JSON-RPC over stdio. Supported methods are listed below.

Lifecycle And Synchronization
-----------------------------

* ``initialize`` and ``initialized``
* ``shutdown`` and ``exit``
* ``textDocument/didOpen``
* ``textDocument/didChange`` (full-document synchronization)
* ``textDocument/didClose``

Navigation And Editing
----------------------

* ``textDocument/declaration``
* ``textDocument/definition``
* ``textDocument/implementation``
* ``textDocument/references``
* ``textDocument/rename``
* ``textDocument/prepareRename`` when the client advertises rename prepare support
* ``textDocument/codeAction`` to add diagnostic suppression comments
* ``textDocument/hover``
* ``textDocument/documentSymbol``
* ``workspace/symbol``
* ``textDocument/documentHighlight``
* ``textDocument/completion`` (commands, packages, variables, and source directives)
* ``textDocument/signatureHelp``
* ``textDocument/foldingRange``
* ``textDocument/documentLink`` for source directives and uniquely resolved
  package sources

Completion triggers are ``$``, ``:``, and ``-``. Signature help triggers are
space and tab.

For a source procedure with active module metadata, definition and declaration
return the source locations first, followed by the metadata declarations.
Implementation returns only source procedures with bodies. When no source
definition is available, definition and declaration can point to metadata alone.

Use :doc:`annotations` to add parameter types, return types, and descriptions
to procedure hover, completion, and signature help.

Diagnostics And Semantic Tokens
-------------------------------

* ``textDocument/publishDiagnostics`` on open, change, and close
* ``textDocument/semanticTokens/full``
* ``textDocument/semanticTokens/full/delta``

Semantic tokens distinguish annotation tags, type names, parameter names,
record fields, literal values, and descriptions in :doc:`annotations`.

Limits
------

Formatting, code lens, and inlay hints are not implemented.
Renaming a body parameter is refused when its source declaration also defines
parameters in other procedures. Use definition to find the shared argument list
and edit it directly if all those procedures should change.

Some features do not yet account for the negotiated position encoding, so
positions after non-ASCII characters can be inaccurate. Code-action request
ranges and text edits use the negotiated encoding.
See :doc:`../user-guide/language-server` for workspace loading behavior and
:doc:`diagnostics` for static analysis limits.
