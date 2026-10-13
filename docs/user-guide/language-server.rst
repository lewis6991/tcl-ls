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

   uv run --project /absolute/path/to/tcl-ls tcl-ls

``--project`` selects the server checkout without changing the working
directory supplied by the editor. Both ``uv`` and ``tclsh`` must be available
in the editor's environment.

Use ``tcllsrc.tcl`` or ``pkgIndex.tcl`` as project root markers if your client
supports them. Otherwise, select the workspace root in the editor.

Workspace Behavior
------------------

The server analyzes open files and loads dependencies from resolvable
``source`` calls, metadata, and ``package require``. It discovers package
indexes near those files and under configured library roots.

Find references also scans unopened ``.tcl``, ``.tm``, and ``.test`` files in
the editor's workspace folders. If the editor supplies no workspace root,
the server uses the nearest ``tcllsrc.tcl`` directory or package root. Open
files use the current editor text. The first search can take longer while the
server analyzes the workspace. Later searches reuse unchanged files, including
after an edit. Command searches limit call resolution to the selected command.
Reference searches skip normal diagnostic checks and refresh cached results
when source files, dependencies, or project settings change.

Project settings come from ``tcllsrc.tcl``. See :doc:`configuration` to add
external libraries, include metadata, or change diagnostics. For unresolved
commands or missing editor features, see :doc:`../support`.
