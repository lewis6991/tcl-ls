CLI Reference
=============

``tcl-ls``
----------

``tcl-ls`` starts the language server on stdio. It does not currently define
additional CLI flags or subcommands.

``tcl-check``
-------------

Usage:

.. code-block:: text

   tcl-check [options] path

Options:

``--color {auto,always,never}``
   Control ANSI color output. ``auto`` only enables color when stdout is a
   terminal and ``NO_COLOR`` is not set.

``--context-lines N``
   Show ``N`` lines of surrounding source context for each diagnostic.

``--fail-on-diagnostics``
   Exit with status 1 if any diagnostics are reported.

``--environment NAME``
   Select an initial tool metadata environment for all checked files. Comment
   directives and conditional project rules can add environments within a file.

``-j, --threads N``
   Analyze source files with ``N`` worker processes. The default is 8.

``--plugin-path PATH``
   Load additional metadata from a directory, a ``.meta.tcl`` file, or a Tcl
   plugin script. The flag may be passed more than once.

Exit behavior:

* ``0`` when analysis completes successfully
* ``1`` for operational failures, or for reported diagnostics when
  ``--fail-on-diagnostics`` is used
* ``130`` when interrupted with ``Ctrl-C``

``tcl-meta``
------------

Usage:

.. code-block:: text

   tcl-meta helper-path
   tcl-meta build-file [--no-probe] [--new-only] [--environment NAME] output.meta.tcl

Subcommands:

``helper-path``
   Print the bundled ``tcl_meta.tcl`` helper path.

``build-file``
   Run the bundled helper through ``tclsh`` and write a ``.meta.tcl`` file.
   Add ``--no-probe`` to inspect definitions without calling discovered commands
   to infer their subcommands. This option also works when the helper is sourced
   inside a tool Tcl shell.

   ``--new-only`` omits commands present in a plain Tcl interpreter, including
   commands replaced by the tool. ``--environment NAME`` writes a named tool
   module with ``-environment``. Without it, output belongs to the ``Tcl`` module.
   Keep reviewed overrides in a separate metadata file loaded after this inventory.

``tcl-meta`` requires ``tclsh`` to be present on ``PATH``.
