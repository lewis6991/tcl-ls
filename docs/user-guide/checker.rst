Project Checking
================

``tcl-check`` reports project diagnostics in the terminal using the same
analysis as the language server.

Run A Check
-----------

Pass a Tcl file or a project directory:

.. code-block:: sh

   tcl-check path/to/file.tcl
   tcl-check path/to/project

Directory checks find ``.tcl``, ``.tm``, and ``.test`` files recursively and
group them into package workspaces using ``pkgIndex.tcl``. Resolved source and
package dependencies provide additional definitions for analysis.

Results are grouped by source file and include a summary. Interactive terminals
also show progress. Add ``--context-lines 2`` to show surrounding source lines.

Use In CI
---------

Diagnostics do not change the default success exit status. To fail when any
enabled diagnostic is reported, use:

.. code-block:: sh

   tcl-check --fail-on-diagnostics path/to/project

Use :ref:`diagnostic-configuration` to choose which diagnostics are reported
and at what severity. The :doc:`../reference/diagnostics` reference lists their
codes and meanings.

Project Settings
----------------

The checker reads ``tcllsrc.tcl`` automatically. Use :doc:`configuration` for
shared metadata, library paths, and tool environment rules.

For a one-off check with additional metadata:

.. code-block:: sh

   tcl-check --meta-path .tcl-ls path/to/project

See :doc:`../reference/cli` for all options, worker settings, and exit statuses.
