Project Configuration
=====================

Both ``tcl-ls`` and ``tcl-check`` read user and project settings from
``tcllsrc.tcl``.
For example:

.. code-block:: tcl

   source .tcl-ls/tools.meta.tcl
   lib-path ../vendor/tcllib
   exclude .venv

Discovery And Syntax
--------------------

Both tools first read ``$XDG_CONFIG_HOME/tcl-ls/tcllsrc.tcl``. If
``XDG_CONFIG_HOME`` is unset, empty, or a relative path, they use
``~/.config/tcl-ls/tcllsrc.tcl`` instead. The user config is optional.

Next, config discovery searches a directory and all its parents, reading
parent settings before child settings:

* The language server starts from each opened file's directory.
* The checker starts from its target directory (or its target file's directory)
  for metadata and library settings.
* Both tools start from each analyzed source file's directory for diagnostic
  and module rules.

Relative paths resolve from the file that contains the declaration.
Each config file is loaded once, even if it is found as both a user config
and an ancestor config. The user config does not set the project's root
directory for reference searches.

Config files accept these commands:

* ``source path`` evaluates another Tcl metadata or config file.
* ``lib-path path`` searches a directory for ``pkgIndex.tcl`` files to resolve
  external packages. ``library-path`` is a synonym.
* ``exclude path`` skips a file or directory during source and package discovery.
* ``meta`` declares metadata directly; see :ref:`project-metadata`.
* ``diagnostic code level ?-path pattern?`` controls diagnostics.
* ``module name`` selects a metadata module for all covered source files.
  Add ``when {condition}`` to select it only where the condition is known
  to be true.

Config files run as Tcl scripts. They can use ``set``, ``if``, ``foreach``,
procedures, and normal Tcl substitutions to choose which settings and metadata
to register. Metadata annotation bodies remain data; they are not executed.
The condition passed to ``module name when {condition}`` describes the analyzed
source and is still analyzed statically, rather than evaluated while loading
the config.

Use config files for settings shared by the editor and checker. For temporary
metadata, use the checker's ``--meta-path`` option; see
:doc:`../reference/cli`.

User Configuration
------------------

The user config accepts the same commands as project configs. Use it to share
metadata, module rules, library paths, and diagnostic settings across checkouts.
For example, add this to ``~/.config/tcl-ls/tcllsrc.tcl`` (or the corresponding
path under ``XDG_CONFIG_HOME``):

.. code-block:: tcl

   source /absolute/path/to/shared/tcllsrc.tcl

The shared file can include metadata and plugins from their original location.
Paths in ``source`` and ``lib-path`` calls remain relative to the file that
contains the call, so the checkouts do not need copies of those files. Ordinary
Tcl substitutions work, including environment-variable references. Use
``file normalize`` when you need to expand ``~`` in a path.

User settings apply to all projects. Project diagnostic rules and metadata
can override them because project configs load later. Library paths accumulate
in config order. Named metadata modules still need selection; loading a user
config does not activate all its modules. See :ref:`module-selection`.

Workspace Context
-----------------

Rc scripts run with their working directory set to the workspace root.
``$::tcl_lsp::context`` is a Tcl dictionary with these keys:

* ``workspace-root``: the absolute path of the matching editor workspace folder.
  Without an editor workspace, use the nearest project config's directory,
  the detected package root, or the source directory, in that order. For a
  checker directory target, use that target directory.
* ``config-path``: the absolute path of the entry rc file being evaluated.
  Use ``info script`` to find the current file inside a sourced script.

For example, a user config can load shared metadata only when the checkout has
no config at the workspace root. File probes start from that root:

.. code-block:: tcl

   if {![file exists tcllsrc.tcl]} {
       source /absolute/path/to/shared/tcllsrc.tcl
   }

This check covers that path only. If a project keeps its config in a
subdirectory, probe that path as well. Other settings in the user config still
apply. You can also probe workspace files through normal Tcl commands:

.. code-block:: tcl

   set root [dict get $::tcl_lsp::context workspace-root]
   if {[file exists [file join $root tool-settings.json]]} {
       source /absolute/path/to/shared/tool.meta.tcl
   }

Each rc file runs once per workspace in a fresh Tcl process while its inputs
stay unchanged. Opening another source file or discovering a dependency reuses
that result. Nested project configs are evaluated when their scope is first
needed, with the same workspace context. Variables and helper procedures
remain available to files it sources. Separate rc files exchange
settings through their registrations, rather than Tcl variables. Different
workspaces keep separate metadata results.

Unchanged declaration syntax is parsed once across workspaces. Identical
registration results also share their metadata model. Rc scripts do not
receive a source-file path. Module conditions are checked during analysis;
they do not cause the rc script to run again.

Saved results are reused while their inputs stay unchanged. Source includes,
files opened for reading, and file probes such as ``file exists`` are checked
again on the next analysis, including paths which were absent. Scripts that
use ``glob`` are evaluated again rather than cached. Changes to the process
environment also cause evaluation again. Changes made through other external
commands are not tracked. Filesystem changes made by rc scripts during
evaluation have undefined behaviour.

Runtime errors stop that rc script and report ``invalid-project-config`` when
editing it. Saved invalid settings prevent ordinary source analysis until they
are corrected. Evaluation has a five-second timeout.

.. _project-metadata:

Metadata Includes
-----------------

``source`` evaluates one file at that position. Included files can include other
files, so a shared metadata file can collect declarations in the required order.
The path must name a file, not a directory.

Metadata can also be declared directly in the config:

.. code-block:: tcl

   meta module ExampleTool {
       source .tcl-ls/tool-commands.meta.tcl
   }

Here, the included declarations belong to ``ExampleTool`` unless they declare
their own module. See :ref:`metadata-composition` for module and include rules,
and :doc:`../meta` for writing or generating metadata.

Discovery Exclusions
--------------------

Use ``exclude`` to keep generated files or unrelated tools out of project scans:

.. code-block:: tcl

   exclude .venv
   exclude generated

Paths are literal file or directory names, without wildcards. Relative paths
start in the declaring file's directory. Excluding a directory also excludes
its descendants, and the scan skips that directory entirely. Exclusions from
user, parent, child, and sourced configs accumulate.

These settings apply to the language server's project reference and unused
procedure scans, package-index discovery, and checker directory targets.
Files opened in the editor or passed directly to the checker are still analyzed.
Explicit ``source`` dependencies and metadata includes are still loaded.

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

Config rules apply in declaration order; the last matching rule wins. A rule
without ``-path`` applies to all files covered by that config, including
subdirectories. In a user config, a rule without ``-path`` applies to all
projects. Path patterns still resolve from the declaring file's directory.

Path patterns are relative to the declaring file's directory and use ``/``
separators. A directory name includes its descendants. ``*``, ``?``, and
``[abc]`` match within one path component; ``**`` matches zero or more
components. Thus, ``vendor/*.tcl`` selects files directly under ``vendor``,
while ``vendor/**/*.tcl`` also selects nested files. Absolute paths and ``..``
components are rejected.

File And Command Directives
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Source comments can override project rules. Use ``diagnostic-file`` to apply a
rule to the whole file, including code before the comment. Place these comments
near the top of the file, after any shebang:

.. code-block:: tcl

   # tcl-ls: diagnostic-file unresolved-variable off

The same form can change a diagnostic's severity:

.. code-block:: tcl

   # tcl-ls: diagnostic-file invalid-expr warning

Use ``diagnostic`` to apply a rule to the next Tcl command:

.. code-block:: tcl

   # tcl-ls: diagnostic unresolved-command off
   tool_command argument

It covers the complete command, including nested bodies and command
substitutions. The command must be in the same Tcl body as the comment. The
rule does not extend to a second command, even on the same line.

Command rules override file rules, which override project rules. Within each
scope, the last matching rule wins. Directives accept the same codes and levels
as project rules, but do not accept ``-path``. They must be Tcl comments; text
inside strings or data words has no effect.

Editor completion offers directive names, diagnostic codes, and levels. Each
item has a short description. Completion replaces the whole word when the
cursor is in its middle. Diagnostic codes can also be wildcard patterns, such
as ``unresolved-*``.

These controls apply to parser and analysis diagnostics in both tools. They do
not disable parsing, symbol resolution, or completion.
``--fail-on-diagnostics`` considers only enabled diagnostics.

Suppression Code Actions
~~~~~~~~~~~~~~~~~~~~~~~~

Use your editor's code-action menu on a diagnostic to add a suppression
comment. The server offers quick fixes for that diagnostic code:

* **Suppress for this command** adds a comment before the smallest enclosing
  command with a safe comment position. For an inline body or command
  substitution, this can be the outer command. The action is omitted if no
  safe position exists.
* **Suppress for this file** adds a file comment after existing file directives,
  or near the start of the file. It preserves a shebang line. The action is
  omitted when a command rule would override it.

The actions preserve indentation and line endings. They do not suppress other
diagnostic codes. They are not marked as preferred fixes, so an editor's
preferred-fix command does not select a suppression automatically.

.. _module-selection:

Module Selection
----------------

Loading metadata makes its named modules available. Selecting a module makes
its commands and embedded languages active. The ``Tcl`` and built-in ``TclOO``
modules are active by default.

``package require name`` selects the module with the same name. Package
requirements in a file and its known dependencies apply to the whole file;
this does not prove runtime execution order. A qualified name such as
``json::json2dict`` does not select its package.

For commands supplied by a tool, select the module with a source directive,
a project rule, or ``tcl-check --module name``.

To enable a module throughout a config's source scope, add this to
``tcllsrc.tcl``:

.. code-block:: tcl

   module ExampleTool

In a user config, this applies to all workspaces where that registration is
made. An rc ``if`` block can restrict it to matching workspaces.

Source Directives
~~~~~~~~~~~~~~~~~

Select a module with a Tcl comment:

.. code-block:: tcl

   if {$use_tool} {
       # tcl-ls: module ExampleTool
       clock -none
   }
   clock seconds

The directive applies from the comment to the end of the enclosing Tcl body.
Nested bodies inherit it and can add another module above it. Leaving a
body restores the previous module. A top-level directive applies to the
rest of the file. Text inside data strings has no effect, and unknown
module names produce diagnostics.

Conditional Rules
~~~~~~~~~~~~~~~~~

A project rule can select a module from known variable values:

.. code-block:: tcl

   module ExampleTool when {$::project::tool eq "example"}

This selects ExampleTool where static analysis knows the condition is true,
such as the matching ``if`` or ``switch`` branch. It does not assert the
condition or execute Tcl commands. An unknown condition does not select the
module. Use fully qualified variable names for project-wide conditions.
Matching rules apply in config order, above explicitly selected modules.

A rule can also name a static environment query:

.. code-block:: tcl

   module ExampleTool when {[cfg_get main tool] eq "example"}

This selects ExampleTool in a matching branch such as
``if {[cfg_get main tool] eq "example" && $enabled} {...}``.
The command name and arguments must be literal words. String comparisons
with ``eq`` and ``ne`` are supported, including reversed operands and negation.
The analyzer matches the configured query without running it. The rule treats
the query as an environment value on that path; it does not infer the query's
implementation or track changes to its backing configuration. Unknown script
execution clears the value. Query results are not procedure requirements.

Guarded Procedure Environments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A normal Tcl guard can establish the condition for the rest of a script:

.. code-block:: tcl

   if {$::project::tool ne "example"} {
       error "This backend requires the example tool"
   }

   namespace eval backend {
       proc run {} {
           tool::check
       }
   }

With the rule above, the continuing path selects ``ExampleTool``. Namespace
values narrowed by guards become requirements of procedures defined on that
path, including procedures inside namespace blocks. Their bodies are checked
under those requirements. Ordinary assignments alone do not establish
procedure requirements, because procedure bodies run later.

These requirements do not make globals immutable. Writes, uncertain variable
links, and dynamic execution invalidate affected facts. An error caught by
``catch`` or a ``try`` handler does not establish a condition after the handler.
Only facts shared by all continuing paths survive a branch join.

Calls to a guarded procedure produce ``incompatible-environment`` warnings
when a known namespace value conflicts with a requirement, including calls
from another file. Unknown calling values do not prove a conflict.

The ``# tcl-ls: module ExampleTool`` directive remains available for explicit
module selection. It does not assign values to tool-selection variables or
add variable requirements to procedures.

Value Tracking Limits
~~~~~~~~~~~~~~~~~~~~~

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

Explicit module directives do not depend on tracked values.

Module Precedence
~~~~~~~~~~~~~~~~~

Package modules are applied in name order, below explicit selections and
matching project rules. Replacing a command from Tcl or a lower
module requires ``meta override``. Embedded languages use the same active
module order; inactive modules do not change them. See
:ref:`metadata-precedence` for replacement rules.

``tcl-check --module name`` selects an initial module for the whole
check. Source directives and conditional rules still apply. Source selections
are local to their file and position and do not affect other open files.

Editing Config Files
--------------------

Files named ``tcllsrc.tcl`` have completion, hover text, signature help, and
navigation for config commands. Invalid entries produce
``invalid-project-config`` diagnostics; incomplete Tcl syntax produces parser
diagnostics. Invalid saved config files prevent their settings from loading.

A config file is analyzed with the other discovered settings, excluding its
own settings, so it can be opened and corrected. Its own diagnostic rules do
not apply to itself, but source directives do. Saved changes take effect when
a source is next analyzed, for example after editing or reopening it.
An unsaved config buffer is evaluated to validate its registrations, but its
settings do not apply to other source buffers until it is saved.
