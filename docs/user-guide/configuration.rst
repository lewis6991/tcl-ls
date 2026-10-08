Project Configuration
=====================

Both ``tcl-ls`` and ``tcl-check`` automatically read project-local config from
``tcllsrc.tcl`` files.

Discovery Rules
---------------

When the server opens a document, or when the checker analyzes a path, the
tool walks upward from that path toward the filesystem root and collects every
``tcllsrc.tcl`` file it finds. Relative paths inside each config file are
resolved relative to the directory that contains that file.

Supported Commands
------------------

``tcllsrc.tcl`` currently supports these static commands:

* ``plugin-path path``
* ``lib-path path``
* ``library-path path``
* ``environment name when {condition}``

Paths must be literal strings. Dynamic Tcl in the config file is rejected.

Typical Example
---------------

.. code-block:: tcl

   plugin-path .tcl-ls
   lib-path ../vendor/tcllib

``plugin-path`` accepts:

* a directory containing ``*.meta.tcl`` files
* a single ``.meta.tcl`` file
* a Tcl plugin script ending in ``.tcl`` or ``.tm``

When a plugin script is passed, sibling metadata files are discovered from the
script's parent directory.

``lib-path`` and ``library-path`` are synonyms. Their directories are scanned
for ``pkgIndex.tcl`` files so external library trees can satisfy
``package require`` without being copied into the main project.

Tool Environments
-----------------

An environment adds a named metadata module above the standard Tcl commands.
Declare the module with ``meta module name -environment`` and load its metadata
with ``plugin-path``. Tool modules are separate from Tcl packages and remain
inactive until selected.

Select an environment in Tcl source with a comment:

.. code-block:: tcl

   if {$use_tool} {
       # tcl-ls: env JasperGold
       clock -none
   }
   clock seconds

The directive applies from the comment to the end of the enclosing Tcl body.
Nested bodies inherit it and can add another environment above it. Leaving a
body restores the previous environment. A top-level directive applies to the
rest of the file. No explicit push or pop is needed. Comments inside data
strings do not select environments. Unknown names produce diagnostics.

For shared code, a project rule can select an environment from known variable
values:

.. code-block:: tcl

   environment JasperGold when {$::fts::TOOL eq "jg"}

The rule does not assert that the condition is true. It selects Jasper where
static analysis knows the condition is true, such as the matching ``if`` or
``switch`` branch. Unknown values do not select it. Conditions use the existing
static expression analysis; Tcl commands are never executed. Use fully qualified
variable names for project-wide conditions. Rules are applied in config order,
above explicitly selected environments.

Each environment can add commands. Replacing a command from Tcl or a lower
environment requires ``meta override``. This keeps generated ``args`` stubs
from hiding precise command metadata.

``tcl-check --environment name`` selects an initial environment for the whole
check. Source directives and conditional rules still apply. Editor environments
are local to the source position and do not affect other open files.

When To Use Config Vs CLI Flags
-------------------------------

Use ``tcllsrc.tcl`` for project settings that should apply to every editor and
checker run. Use the ``tcl-check --plugin-path`` flag for temporary or
one-off metadata injection.
