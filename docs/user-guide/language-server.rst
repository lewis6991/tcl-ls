Language Server
===============

Use the supplied :doc:`neovim` config or :doc:`vscode` extension, or configure
another LSP client as described below. The :doc:`../reference/lsp-features`
reference lists supported features and protocol limits.

Connecting An Editor
--------------------

Configure the client to launch ``tcl-ls`` over stdio for Tcl files. The command
must be available in the editor's environment. An absolute executable path
can help if a GUI editor has a different ``PATH`` from your terminal.

For a development checkout prepared as described in :doc:`../development`,
use:

.. code-block:: sh

   uv run --directory /absolute/path/to/tcl-ls tcl-ls

Use ``tcllsrc.tcl`` or ``pkgIndex.tcl`` as project root markers if your client
supports them. Otherwise, select the workspace root in the editor.

Workspace Behavior
------------------

The server analyzes open files and loads dependencies from resolvable
``source`` calls, metadata, and ``package require``. It discovers package
indexes near those files and under configured library roots. It does not scan
every Tcl source in the workspace.

Project settings come from ``tcllsrc.tcl``. See :doc:`configuration` to add
external libraries, include metadata, or change diagnostics. For unresolved
commands or missing editor features, see :doc:`../support`.
