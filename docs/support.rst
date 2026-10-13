Support
=======

Troubleshooting
---------------

Editor features are missing
   Check that the file has the Tcl filetype and the client can launch the
   configured server. Check the editor's LSP log for startup errors. See
   :doc:`user-guide/language-server` or the editor-specific setup guide.

The server reports that ``tclsh`` is missing
   Install Tcl and make ``tclsh`` available on the editor's ``PATH``. The
   server and checker require it even when no project plugin is configured.
   Prebuilt servers remove the Python requirement but still need ``tclsh``.

Commands are unresolved
   Check that the source file is below the intended ``tcllsrc.tcl``. Include
   metadata for custom commands and select the required tool module;
   see :ref:`project-metadata` and :ref:`module-selection`.

Packages are unresolved
   Check that the library contains a ``pkgIndex.tcl`` and add its directory
   with ``lib-path``. Package indexes and dependencies must be statically
   resolvable; see :doc:`user-guide/configuration`.

Saved settings or plugin changes appear unchanged
   Save the config, metadata, or Tcl plugin file, then reopen or edit a source
   file to trigger analysis, or restart the language server. VS Code watches
   config files, package indexes, and ``*.meta.tcl`` for automatic restarts.
   Ordinary Tcl plugin scripts are not watched; see :doc:`user-guide/vscode`.

For diagnostic meanings and analysis limits, see :doc:`reference/diagnostics`.

Reporting A Problem
-------------------

Include the following in a
`GitHub issue <https://github.com/lewis6991/tcl-ls/issues>`_:

* the smallest Tcl example that reproduces the problem
* the expected result and the actual diagnostic or error
* the command, or editor and LSP configuration, used to reproduce it
* relevant ``tcllsrc.tcl``, metadata, and package index files
* the tcl-ls version or commit, operating system, and installation method

For an editor diagnostic, check whether the batch checker reports the same
problem:

.. code-block:: sh

   tcl-check --context-lines 2 path/to/example.tcl

Include that output and any relevant editor LSP log entries.
