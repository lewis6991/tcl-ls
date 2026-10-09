Project Configuration
=====================

Both ``tcl-ls`` and ``tcl-check`` read project settings from ``tcllsrc.tcl``.
For example:

.. code-block:: tcl

   source .tcl-ls/tools.meta.tcl
   lib-path ../vendor/tcllib

Discovery And Syntax
--------------------

Config discovery searches a directory and all its parents, reading parent
settings first:

* The language server starts from each opened file's directory.
* The checker starts from its target directory (or its target file's directory)
  for metadata and library settings.
* Both tools start from each analyzed source file's directory for diagnostic
  and environment rules.

Relative paths resolve from the file that contains the declaration.

Config files accept these commands:

* ``source path`` includes a file of metadata or config declarations.
* ``lib-path path`` searches a directory for ``pkgIndex.tcl`` files to resolve
  external packages. ``library-path`` is a synonym.
* ``meta`` declares metadata directly; see :ref:`project-metadata`.
* ``diagnostic code level ?-path pattern?`` controls diagnostics.
* ``environment name when {condition}`` selects a tool environment when a
  condition is known to be true.

Config files are read as static declarations. Paths and other arguments must
be literal Tcl words; Tcl commands are not executed. Brace conditions and words
that contain spaces or brackets.

Use config files for settings shared by the editor and checker. For temporary
metadata, use the checker's ``--meta-path`` option; see
:doc:`../reference/cli`.

.. _project-metadata:

Metadata Includes
-----------------

``source`` includes one file at that position. Included files can include other
files, so a shared metadata file can collect declarations in the required order.
The path must name a file, not a directory.

Metadata can also be declared directly in the config:

.. code-block:: tcl

   meta module JasperGold -environment {
       source .tcl-ls/jasper-commands.meta.tcl
   }

Here, the included declarations belong to ``JasperGold`` unless they declare
their own module. See :ref:`metadata-composition` for module and include rules,
and :doc:`../meta` for writing or generating metadata.

.. _diagnostic-configuration:

Diagnostic Controls
-------------------

Use ``diagnostic`` to change severity or disable a diagnostic:

.. code-block:: tcl

   diagnostic unresolved-variable off
   diagnostic unresolved-command error
   diagnostic unknown-option hint -path vendor
   diagnostic * off -path generated/**
   diagnostic unresolved-command default -path generated/handwritten.tcl

Levels are ``error``, ``warning``, ``information``, ``hint``, ``off``, and
``default``. ``off`` disables a diagnostic. ``default`` enables it at its
built-in severity, including when an earlier rule disabled it. Codes accept
wildcards, such as ``unresolved-*`` or ``*`` for all diagnostics. See the
:doc:`diagnostic catalog <../reference/diagnostics>` for available codes.

Project rules apply in declaration order; the last matching rule wins. A rule
without ``-path`` applies to all files covered by that config, including
subdirectories.

Path patterns are relative to the declaring file's directory and use ``/``
separators. A directory name includes its descendants. ``*``, ``?``, and
``[abc]`` match within one path component; ``**`` matches zero or more
components. Thus, ``vendor/*.tcl`` selects files directly under ``vendor``,
while ``vendor/**/*.tcl`` also selects nested files. Absolute paths and ``..``
components are rejected.

File And Statement Directives
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Source comments can override project rules. A ``file`` directive applies to the
whole file, including code before the comment:

.. code-block:: tcl

   # tcl-ls: diagnostic file unresolved-variable off

A ``statement`` directive applies to the next Tcl statement:

.. code-block:: tcl

   # tcl-ls: diagnostic statement unresolved-command off
   tool_command argument

It covers the complete statement, including nested bodies and command
substitutions. The statement must be in the same Tcl body as the comment. The
rule does not extend to a second statement, even on the same line.

Statement rules override file rules, which override project rules. Within each
scope, the last matching rule wins. Directives accept the same codes and levels
as project rules, but do not accept ``-path``. They must be Tcl comments; text
inside strings or data words has no effect.

These controls apply to parser and analysis diagnostics in both tools. They do
not disable parsing, symbol resolution, or completion.
``--fail-on-diagnostics`` considers only enabled diagnostics.

.. _tool-environments:

Tool Environments
-----------------

An environment adds a named metadata module above the standard Tcl commands.
Declare it with ``meta module name -environment {body}``, as above. Loading the
metadata makes the environment available; selecting it makes its commands
active. Environments are separate from Tcl packages.

Source Directives
~~~~~~~~~~~~~~~~~

Select an environment with a Tcl comment:

.. code-block:: tcl

   if {$use_tool} {
       # tcl-ls: env JasperGold
       clock -none
   }
   clock seconds

The directive applies from the comment to the end of the enclosing Tcl body.
Nested bodies inherit it and can add another environment above it. Leaving a
body restores the previous environment. A top-level directive applies to the
rest of the file. Text inside data strings has no effect, and unknown
environment names produce diagnostics.

Conditional Rules
~~~~~~~~~~~~~~~~~

A project rule can select an environment from known variable values:

.. code-block:: tcl

   environment JasperGold when {$::fts::TOOL eq "jg"}

This selects JasperGold where static analysis knows the condition is true,
such as the matching ``if`` or ``switch`` branch. It does not assert the
condition or execute Tcl commands. An unknown condition does not select the
environment. Use fully qualified variable names for project-wide conditions.
Matching rules apply in config order, above explicitly selected environments.

Value tracking has these limits:

* Visible assignments and metadata ``bind`` effects update tracked values.
  After a branch, a value is known only if every possible path establishes it.
* Loops and caught errors invalidate variables their bodies may write.
  Dynamic execution, such as ``eval`` or ``source``, discards tracked values.
* Writes inside called procedures are not inferred. Use ``bind`` metadata to
  describe writes to caller variables.
* Qualified names and their namespace-local spellings refer to the same
  variable. Procedure locals remain separate unless ``global`` or ``variable``
  links them. Uncertain links are treated as unknown.

Explicit environment directives do not depend on tracked values.

Environment Precedence
~~~~~~~~~~~~~~~~~~~~~~

Environments can add commands. Replacing a command from Tcl or a lower
environment requires ``meta override``. Embedded languages use the same active
environment order; inactive environments do not change them. See
:ref:`metadata-precedence` for replacement rules.

``tcl-check --environment name`` selects an initial environment for the whole
check. Source directives and conditional rules still apply. Editor environments
are local to the source position and do not affect other open files.

Editing Config Files
--------------------

Files named ``tcllsrc.tcl`` have completion, hover text, signature help, and
navigation for config commands. Invalid entries produce
``invalid-project-config`` diagnostics; incomplete Tcl syntax produces parser
diagnostics. Invalid saved config files prevent their settings from loading.

A config file is analyzed with its parent settings, excluding its own settings,
so it can be opened and corrected. Its own diagnostic rules do not apply to
itself, but source directives do. Saved changes take effect when a source is
next analyzed, for example after editing or reopening it.
