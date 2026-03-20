Project Checking
================

``tcl-check`` runs the same parser, metadata registry, and resolver used by
the language server, but reports diagnostics in a terminal-friendly format.

Common Commands
---------------

Analyze a directory or a single file:

.. code-block:: sh

   uv run tcl-check path/to/project
   uv run tcl-check path/to/file.tcl

Show source context and fail the command when diagnostics are present:

.. code-block:: sh

   uv run tcl-check --context-lines 2 --fail-on-diagnostics path/to/project

Load extra project metadata explicitly:

.. code-block:: sh

   uv run tcl-check --plugin-path .tcl-ls path/to/project

Control worker count:

.. code-block:: sh

   uv run tcl-check --threads 4 path/to/project

What The Checker Does
---------------------

The checker prepares package-scoped workspaces, indexes source files, and then
prints grouped diagnostics with a summary at the end. In an interactive
terminal, it also shows live progress as workspaces and source files are
analyzed.

The checker currently focuses on high-confidence diagnostics, including areas
such as:

* unresolved commands, packages, and variables
* ambiguous command or variable resolution
* duplicate procedures
* malformed static command forms such as ``if`` and ``switch``
* metadata-driven option, subcommand, and arity checks

For the full diagnostic catalog and severity/source conventions, see
:doc:`../reference/diagnostics`.

Project And Dependency Discovery
--------------------------------

``tcl-check`` understands local package layouts instead of treating every file
as an isolated script:

* ``pkgIndex.tcl`` roots define package workspaces
* dependent files can be pulled in as background sources when package metadata
  points at them
* ``lib-path`` and ``library-path`` extend the set of external package roots
* ``plugin-path`` adds extra metadata files or Tcl plugin helpers

For repeated workflows against the bundled ``tcllib`` checkout in this
repository, use:

.. code-block:: sh

   make check-tcllib
