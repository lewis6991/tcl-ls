Language Server
===============

The ``tcl-ls`` command starts a JSON-RPC language server over stdio. It does
not currently expose standalone flags or subcommands, so most editor setups
only need a command and a Tcl file association.

Connecting An Editor
--------------------

Point your LSP client at one of these commands:

* ``tcl-ls`` if the package is installed into your environment
* ``uv run tcl-ls`` when working from a repository checkout

In practice, editor setups usually also want:

* Tcl filetypes such as ``.tcl`` and ``.tm``
* a project root marker such as ``tcllsrc.tcl``, ``pkgIndex.tcl``, or ``.git``
* stdio transport instead of TCP

Workspace Behavior
------------------

The server builds its view of the workspace when a document is opened. It
loads project config from any ``tcllsrc.tcl`` files found between the opened
file and the filesystem root, then uses that config to discover extra metadata
and package roots.

Package discovery is conservative:

* directories rooted by ``pkgIndex.tcl`` are treated as package workspaces
* external library roots can be added through ``lib-path`` or ``library-path``
* extra metadata can be added through ``plugin-path``

Supported Editor Features
-------------------------

The current server supports:

* diagnostics on open, change, and close
* go to definition
* find references
* rename
* hover
* document symbols
* workspace symbols
* command, package, and variable completion
* signature help
* semantic tokens
* document highlights

Current Limits
--------------

The server is usable, but it is still an early implementation:

* text synchronization is full-document only
* dynamic Tcl constructs are intentionally analyzed conservatively
* unopened files are discovered opportunistically rather than through full
  workspace scanning
* code actions, formatting, code lens, and inlay hints are not implemented yet
* no editor plugin package ships in this repository; clients need manual LSP
  configuration

