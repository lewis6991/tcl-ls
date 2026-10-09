CLI Reference
=============

``tcl-ls``
----------

Starts the language server over stdio. It has no additional flags or
subcommands. See :doc:`../user-guide/language-server` for editor setup.

``tcl-check``
-------------

.. code-block:: text

   tcl-check [options] path

``path`` is a source file or project directory. Project config is read
automatically; see :doc:`../user-guide/configuration`.

``--color {auto,always,never}``
   Control ANSI color output. The default, ``auto``, enables color only when
   stdout is a terminal and ``NO_COLOR`` is not set.

``--context-lines N``
   Show ``N`` surrounding source lines for each diagnostic. Default: 0.
   ``N`` must be nonnegative.

``--fail-on-diagnostics``
   Exit with status 1 if any enabled diagnostic is reported, at any severity.

``--environment NAME``
   Select an initial tool environment. Source directives and project rules
   can add environments within a file; see :ref:`tool-environments`.

``-j, --threads N``
   Use ``N`` worker processes. Default: 8. ``N`` must be at least 1.

``--meta-path PATH``
   Load additional metadata after the project config. Repeat the flag to add
   paths in order. A directory is searched recursively for ``*.meta.tcl``;
   a ``.meta.tcl`` file is read directly. A Tcl plugin script path (``.tcl`` or
   ``.tm``) selects its parent directory for metadata discovery. This flag does
   not execute the plugin script.

Exit statuses:

* ``0``: analysis completed; diagnostics are allowed unless
  ``--fail-on-diagnostics`` is set
* ``1``: an operational failure, or diagnostics with ``--fail-on-diagnostics``
* ``2``: invalid command-line arguments
* ``130``: interrupted with ``Ctrl-C``

``tcl-meta``
------------

.. code-block:: text

   tcl-meta helper-path
   tcl-meta build-file [options] output.meta.tcl

``helper-path`` prints the bundled Tcl helper's path. ``build-file`` runs it
through ``tclsh`` and writes metadata to the output file. The latter requires
``tclsh`` on ``PATH``. To generate metadata in a tool's own interpreter,
follow :doc:`../meta`.

``build-file`` options:

``--no-probe``
   Inspect definitions without calling discovered commands. By default, the
   helper calls commands with test arguments to infer subcommands.

``--new-only``
   Exclude names present in plain Tcl, including commands replaced by the tool.
   By default, the inventory also includes Tcl commands whose introspected
   shape differs from the plain interpreter.

``--environment NAME``
   Write a tool module declared with ``-environment``. Default: ``Tcl``, which
   writes ordinary Tcl module metadata.

``--include-commands LIST``
   Add command names from a Tcl list to the discovered inventory. Each name
   must resolve in the active interpreter. Use this when a tool filters
   ``info commands`` or provides its own catalogue. May be repeated; the
   other generation options also apply to these commands.

``--internal-commands LIST``
   Include existing commands and mark them ``-visibility internal``. Accepts
   a Tcl list and may be repeated. All other commands default to public;
   the helper does not infer visibility from names.

The same options are accepted when the Tcl helper is sourced in a tool shell.
