Metadata And Meta Tools
=======================

``tcl-ls`` relies on declarative metadata to understand builtin Tcl commands
and project-specific command behavior. The repository ships a bundled metadata
registry under ``meta/``, and both the language server and checker can load
extra metadata from project config or CLI flags.

Metadata Discovery
------------------

The active metadata registry is assembled from:

* the bundled ``meta/`` directory shipped with the package
* any paths provided by ``plugin-path`` in ``tcllsrc.tcl``
* any paths passed through ``tcl-check --plugin-path``

Directories are scanned recursively for ``*.meta.tcl`` files. A direct
``.meta.tcl`` path is loaded as-is. A ``.tcl`` or ``.tm`` plugin path causes
the containing directory to be scanned for sibling metadata files.

Basic Metadata Shape
--------------------

Metadata files use ``meta`` commands:

.. code-block:: tcl

   # Leading comments become command documentation.
   meta command regexp {args} {
       option -start value
       option -- stop
       bind after-options 3..
   }

The command name and signature must be static. Leading comments are used as
documentation for hover and completion details.

For the full declaration grammar, selector rules, annotation forms, and Tcl
plugin contract, see :doc:`reference/meta-syntax`.

Supported Annotations
---------------------

Common annotations:

* ``option`` describes flag, value, and ``--`` handling
* ``subcommand`` declares nested command names
* ``bind`` marks arguments that introduce variable bindings
* ``ref`` marks arguments that reference variables
* ``script-body`` reparses selected arguments as Tcl bodies
* ``source`` records sourced files relative to the call site or procedure file
* ``package`` records required packages

Advanced annotations:

* ``context`` defines a named command-body context
* ``procedure`` describes commands that declare procedures or methods
* ``plugin`` links a metadata entry to a Tcl-side plugin procedure

Selectors are 1-based and can target single arguments, ranges such as ``3..``,
or reverse offsets such as ``last`` and ``last-1``. They also support
``after-options``, ``list``, and ranged ``step N`` forms for commands that
need more precise argument modeling.

Meta Helper CLI
---------------

``tcl-meta`` exposes the bundled helper script used for tool-specific metadata
generation:

.. code-block:: sh

   uv run tcl-meta helper-path
   uv run tcl-meta build-file path/to/output.meta.tcl

``helper-path`` prints the bundled ``tcl_meta.tcl`` path so a tool-specific
Tcl shell can ``source`` it directly. ``build-file`` runs the same helper via
``tclsh`` and writes a ``.meta.tcl`` file to the requested output path.

When To Reach For Metadata
--------------------------

Add metadata when the analyzer needs help understanding project-specific Tcl
APIs that are otherwise too dynamic to infer safely, such as:

* commands with option-driven argument shapes
* commands that execute callback bodies
* wrappers around ``source`` or ``package require``
* plugin-defined commands that should participate in hover, completion, or
  diagnostics
