Support
=======

Troubleshooting
---------------

Editor features are missing
   Check that the file has the Tcl filetype and the client can launch the
   configured server. Check the editor's LSP log for startup errors. See
   :doc:`user-guide/language-server` or the editor-specific setup guide.

Commands are unresolved
   Check that the source file is below the intended ``tcllsrc.tcl``. Include
   metadata for custom commands and select the required tool environment;
   see :ref:`project-metadata` and :ref:`tool-environments`.

Packages are unresolved
   Check that the library contains a ``pkgIndex.tcl`` and add its directory
   with ``lib-path``. Package indexes and dependencies must be statically
   resolvable; see :doc:`user-guide/configuration`.

Saved settings appear unchanged
   Reopen or edit the source file to trigger analysis, or restart the language
   server. The VS Code extension can restart automatically when project files
   change; see :doc:`user-guide/vscode`.

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
