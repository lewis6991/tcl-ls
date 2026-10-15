Diagnostics
===========

The language server and ``tcl-check`` report the same diagnostic codes. Each
diagnostic has a code, message, severity, source, and source location.

Severity And Source
-------------------

All diagnostics default to ``error``, except resolution diagnostics,
possible value constraint failures, and environment conflicts (``warning``),
and ``unreachable-code`` (``hint``). Project rules and source comments can
change severity or disable diagnostics for files or commands;
see :ref:`diagnostic-configuration`.

The ``source`` field identifies the origin:

* ``parser``: Tcl syntax errors.
* ``analysis``: command structure, resolution, and metadata checks.
* ``tcl-ls``: invalid config entries or source directives.

Parser Diagnostics
------------------

``unmatched-quote``
   A quoted word started with ``"`` but did not close.

``unmatched-brace``
   A braced word started with ``{`` but did not close.

``unmatched-bracket``
   A command substitution started with ``[`` but did not close.

``malformed-variable``
   A variable substitution, such as ``${name}``, is incomplete or malformed.

Configuration And Directive Diagnostics
---------------------------------------

``invalid-project-config``
   A config declaration is unsupported, has invalid arguments, or uses dynamic
   values where static words are required. This also covers metadata and
   include errors found when validating ``tcllsrc.tcl``.

``invalid-diagnostic-directive``
   A diagnostic comment has invalid syntax or level, or a command
   directive has no following command in its Tcl body.

``invalid-module``
   A module comment has invalid syntax or names an unknown module.

Structural Diagnostics
----------------------

``malformed-if``
   A statically analyzable ``if`` command has an invalid word layout.

``malformed-switch``
   A statically analyzable ``switch`` command has an invalid option or branch
   layout.

``duplicate-proc``
   The same qualified procedure name is declared more than once in the active
   workspace.

``unreachable-code``
   A command cannot run because an earlier command always leaves the script or
   a statically known condition excludes its branch.

``incompatible-environment``
   A known namespace value at a call conflicts with a condition required by the
   called procedure. Requirements come from guards on the path that defines
   the procedure.

Resolution Diagnostics
----------------------

``unresolved-command``
   A command call could not be resolved to a builtin, procedure, or command
   described by metadata.

``ambiguous-command``
   A command name matched multiple procedure candidates.

``unresolved-package``
   A ``package require`` target was not found in builtin metadata or discovered
   package roots.

``unresolved-variable``
   A procedure-scoped variable reference could not be resolved confidently.

``ambiguous-variable``
   A procedure-scoped variable reference matched multiple bindings.

Command And Metadata Diagnostics
--------------------------------

``wrong-argument-count``
   A command call has too few or too many arguments for its known signatures.

``invalid-arguments``
   The argument count matches a signature, but the arguments do not match its
   required structure or literal values.

``unknown-subcommand``
   The first positional argument does not match a known subcommand.

``unknown-option``
   An option does not match any declared option for the resolved command.

``missing-option-value``
   An option that requires a value has no following value.

``invalid-regex``
   A statically known pattern for ``regexp`` or ``regsub`` fails Tcl regular
   expression compilation.

``invalid-expr``
   An expression has invalid syntax within the supported expression grammar.
   The message gives the parser's reason, followed by the expression text
   after known substitutions on a separate line. Reasons include invalid bare
   words, missing operands or operators, incomplete conditional expressions,
   and unclosed delimiters.
   The default severity is ``warning`` when only some known expression texts
   fail this check. ``Possible expansion`` shows a failing alternative for a
   warning; ``Example expansion`` shows one when all alternatives fail.
   Syntax must be valid even in a branch skipped by a short-circuit operator.

``invalid-expr-operand``
   A known operand does not satisfy an operator's numeric, integer, truth, or
   list requirement. The default severity is ``warning`` when only some known
   alternatives fail. Unknown inputs do not produce this diagnostic.

``invalid-value``
   A known value assigned by ``set`` does not satisfy its ``@type`` annotation.
   The default severity is ``warning`` when only some known values fail.
   See :ref:`value-constraints` for supported checks and examples.

``conflicting-embedded-language``
   Metadata ``enter`` clauses select overlapping command bodies.

``unsupported-special-enter``
   An ``enter body`` selector for a structured Tcl command does not select one
   existing script-body argument. See :doc:`meta-syntax` for selector rules.

Analysis Limits
---------------

Diagnostics depend on what static analysis can establish. Dynamic values can
prevent a check, and metadata checks require sufficiently confident command
resolution. The tools do not evaluate project Tcl code to detect runtime
errors. Keep metadata current so checks reflect the commands available to the
program.
