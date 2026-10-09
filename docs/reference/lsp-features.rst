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
* ``textDocument/hover``
* ``textDocument/documentSymbol``
* ``workspace/symbol``
* ``textDocument/documentHighlight``
* ``textDocument/completion`` (commands, packages, and variables)
* ``textDocument/signatureHelp``
* ``textDocument/foldingRange``
* ``textDocument/documentLink`` for source directives and uniquely resolved
  package sources

Completion triggers are ``$``, ``:``, and ``-``. Signature help triggers are
space and tab.

Diagnostics And Semantic Tokens
-------------------------------

* ``textDocument/publishDiagnostics`` on open, change, and close
* ``textDocument/semanticTokens/full``
* ``textDocument/semanticTokens/full/delta``

Limits
------

Code actions, formatting, code lens, and inlay hints are not implemented.
Position conversion does not yet account for the negotiated encoding, so
positions after non-ASCII characters can be inaccurate.
See :doc:`../user-guide/language-server` for workspace loading behavior and
:doc:`diagnostics` for static analysis limits.
