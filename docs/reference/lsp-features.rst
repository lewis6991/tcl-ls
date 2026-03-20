LSP Features
============

The server currently exposes a compact but useful LSP surface focused on
navigation, diagnostics, and conservative semantic analysis.

Core Lifecycle
--------------

Supported protocol methods include:

* ``initialize``
* ``initialized``
* ``shutdown``
* ``exit``
* ``textDocument/didOpen``
* ``textDocument/didChange``
* ``textDocument/didClose``

Navigation And Intelligence
---------------------------

The current server supports:

* ``textDocument/declaration``
* ``textDocument/definition``
* ``textDocument/implementation``
* ``textDocument/references``
* ``textDocument/rename``
* ``textDocument/prepareRename`` when the client advertises rename prepare
  support
* ``textDocument/hover``
* ``textDocument/documentSymbol``
* ``workspace/symbol``
* ``textDocument/documentHighlight``
* ``textDocument/completion``
* ``textDocument/signatureHelp``
* ``textDocument/foldingRange``
* ``textDocument/documentLink``

Completion is triggered by ``$``, ``:``, and ``-``. Signature help is triggered
by a space or tab after the command name and earlier arguments.

Semantic Output
---------------

The server publishes diagnostics and semantic tokens for open documents:

* ``textDocument/publishDiagnostics`` on open, change, and close
* ``textDocument/semanticTokens/full``
* ``textDocument/semanticTokens/full/delta``

Implementation Limits
---------------------

The current protocol implementation still has some notable limits:

* text synchronization is full-document only
* position handling does not yet negotiate a custom ``positionEncoding``
* automatic workspace discovery is limited; unopened files are indexed
  conservatively through package inference rather than full file watching
* code actions, formatting, code lens, and inlay hints are not implemented
