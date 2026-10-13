Writing And Generating Metadata
===============================

Metadata describes command signatures and behavior that static analysis cannot
infer from Tcl source. Use it for tool commands, callback bodies, variable
bindings, and wrappers around ``source`` or ``package require``. The language
server and checker use the same metadata for diagnostics. The server also uses
it for navigation, hover, and completion.

Load Project Metadata
---------------------

The bundled ``meta/`` directory describes Tcl and supported packages. To add
project metadata, include a file from ``tcllsrc.tcl``:

.. code-block:: tcl

   source .tcl-ls/project.meta.tcl

Paths are relative to the containing file. Metadata files can include other
files with ``source``; these are static declarations, not Tcl execution. See
:ref:`metadata-composition` for module scope and :ref:`metadata-precedence` for
override rules.

For a one-off checker run, use ``tcl-check --meta-path``. It accepts a metadata
file or directory; see :doc:`reference/cli` for path discovery rules.

Describe A Command
------------------

Create ``.tcl-ls/project.meta.tcl`` with a module block:

.. code-block:: tcl

   meta module Tcl {
       # Run a script with a package loaded and store its result.
       meta command project::run {packageName script resultVar} {
           package {select 1}
           enter tcl body 2
           bind 3 set
       }
   }

The shape ``{packageName script resultVar}`` describes three arguments.
Annotations record the package dependency, parse the script body, and bind the
result variable. Selectors count arguments from 1. Leading comments supply
command documentation.

Use the ``Tcl`` module for commands available throughout the project, a package
name for package commands, or a tool name such as ``JasperGold``. See
:ref:`module-selection` for activation through package requirements, project
rules, and source comments.

For more command models, see the :doc:`reference/meta-syntax`:

* ``option`` and nested ``command`` describe flags and subcommands.
* ``bind`` and ``ref`` describe variable writes and references.
* ``meta language``, ``enter``, and ``procedure`` describe embedded scripts and
  procedure declarations.
* ``source`` and ``package`` describe dependencies.
* ``meta alias`` reuses metadata for an alias or renamed command.
* ``plugin`` calls a Tcl hook when declarations cannot express the behavior.

Generate A Tool Inventory
-------------------------

``tcl-meta`` can inspect commands in a tool's Tcl interpreter. First, locate
the bundled helper:

.. code-block:: sh

   tcl-meta helper-path

Source that path inside the tool, then generate its command inventory.
Generation requires ``tclsh`` on ``PATH`` to obtain a plain Tcl baseline:

.. code-block:: tcl

   source /path/printed/by/helper-path/tcl_meta.tcl
   tcl-meta build-file --no-probe --new-only --module JasperGold jasper.meta.tcl

This example inspects definitions without calling tool commands. It keeps
procedure parameters, uses ``args`` for native commands, and excludes names
present in plain Tcl. Without ``--no-probe``, the helper calls commands with
test arguments to infer subcommands. See :doc:`reference/cli` for all options
and the standalone ``tclsh`` workflow.

Keep reviewed signatures, annotations, and replacements in a separate file so
regeneration preserves them. Load that file after the inventory:

.. code-block:: tcl

   # .tcl-ls/project.meta.tcl
   source jasper.meta.tcl
   source jasper-overrides.meta.tcl

For example, ``jasper-overrides.meta.tcl`` can declare a tool replacement and
retain metadata for the original Tcl command under its renamed name:

.. code-block:: tcl

   meta module JasperGold {
       meta override clock {args}
       meta alias tcl_clock clock -module Tcl
   }

Replace the general ``args`` shape with a precise signature when available.
