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
files with ``source``. Files sourced from an rc script run as Tcl and can use
control flow to generate declarations. Annotation bodies remain data. Metadata
loaded directly through ``--meta-path`` uses static declarations. See
:doc:`user-guide/configuration` for rc evaluation, :ref:`metadata-composition`
for module scope, and :ref:`metadata-precedence` for override rules.

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
name for package commands, or a tool name such as ``ExampleTool``. See
:ref:`module-selection` for activation through package requirements, project
rules, and source comments.

For more command models, see the :doc:`reference/meta-syntax`:

* ``option`` and nested ``command`` describe flags and subcommands.
* ``bind`` and ``ref`` describe variable writes and references.
* ``call`` describes a command name and arguments forwarded by a wrapper.
* ``meta language``, ``enter``, and ``procedure`` describe embedded scripts and
  procedure declarations.
* ``source`` and ``package`` describe dependencies.
* ``meta alias`` reuses metadata for an alias or renamed command.
* ``plugin`` calls a Tcl hook when declarations cannot express the behavior.

Describe Procedure Parameters
-----------------------------

Use ``procedure`` when a command declares a procedure. Keep its name, parameters,
and body in separate fields:

.. code-block:: tcl

   meta module Tcl {
       meta command project::define {name parameters body} {
           procedure {
               name {select 1}
               params {select 2}
               body {select 3}
           }
       }
   }

This example accepts a standard Tcl parameter list. The analyzer can also read a
known literal variable value, such as ``project::define prove $common_args {...}``.
Parameter definitions retain their original source locations. Braced arguments
keep variable references literal.

For a custom parameter syntax, add a parser hook to ``params``:

.. code-block:: tcl

   params {
       select 2
       plugin {options.tcl ::project::metadata::parameters}
   }

The hook receives a source-item dictionary for the selected argument. It returns
IDs for the source items that name the body parameters. The metadata still
selects the procedure name and body. The script path is relative to the metadata
file. See :ref:`metadata-parameter-parsers` for a complete example and
:ref:`metadata-procedures` for all field settings.

Update Older Metadata
---------------------

Procedure fields and package annotations require braced key/value lists.
Replace ``name select 1`` with ``name {select 1}``, and replace
``package select 1`` with ``package {select 1}``. Literal values use the same
form, such as ``params {literal {target args}}``.

The old Tepam parameter formats are no longer supported. Use a ``params`` parser
hook for custom declarations. The bundled Tepam metadata provides its own hook;
project wrappers can provide a separate hook for their behavior.

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
   tcl-meta build-file --no-probe --new-only --module ExampleTool tool.meta.tcl

This example inspects definitions without calling tool commands. It keeps
procedure parameters, uses ``args`` for native commands, and excludes names
present in plain Tcl. Without ``--no-probe``, the helper calls commands with
test arguments to infer subcommands. See :doc:`reference/cli` for all options
and the standalone ``tclsh`` workflow.

Keep reviewed signatures, annotations, and replacements in a separate file so
regeneration preserves them. Load that file after the inventory:

.. code-block:: tcl

   # .tcl-ls/project.meta.tcl
   source tool.meta.tcl
   source tool-overrides.meta.tcl

For example, ``tool-overrides.meta.tcl`` can declare a tool replacement and
retain metadata for the original Tcl command under its renamed name:

.. code-block:: tcl

   meta module ExampleTool {
       meta override clock {args}
       meta alias tcl_clock clock -module Tcl
   }

Replace the general ``args`` shape with a precise signature when available.
