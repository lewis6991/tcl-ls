Diagnostics
===========

``tcl-ls`` emits diagnostics from two stages:

* the parser, which reports Tcl syntax and tokenization problems
* the analysis pipeline, which reports structural and semantic issues in code
  that parsed successfully enough to continue analysis

The same diagnostic set is used by both ``tcl-check`` and the language server.
In CLI output you see the formatted message, code, and source context. In LSP
clients, diagnostics are published with ``code``, ``source``, ``severity``, and
``message`` fields.

Sources And Severity
--------------------

Diagnostic ``source`` values:

* ``parser`` for syntax diagnostics
* ``analysis`` for lowering, resolution, metadata-driven, and semantic
  diagnostics

Current severity conventions:

* parser diagnostics are errors
* malformed static command forms are errors
* metadata and arity validation failures are errors
* unresolved and ambiguous resolution results are warnings

Parser Diagnostics
------------------

These come directly from the Tcl parser:

``unmatched-quote``
   A quoted word started with ``"`` but did not close.

``unmatched-brace``
   A braced word started with ``{`` but did not close.

``unmatched-bracket``
   A command substitution started with ``[`` but did not close.

``malformed-variable``
   A variable substitution such as ``${name}`` is syntactically incomplete or
   malformed.

Structural Analysis Diagnostics
-------------------------------

These are emitted while lowering and normalizing certain Tcl forms before the
main semantic pass.

``malformed-if``
   A statically analyzable ``if`` command has an invalid word layout.

``malformed-switch``
   A statically analyzable ``switch`` command has an invalid option or branch
   layout.

Semantic And Resolution Diagnostics
-----------------------------------

These are emitted by the semantic resolver and diagnostic checkers.

Warnings:

``unresolved-command``
   A command call could not be resolved to a builtin command, procedure, or
   metadata-backed command.

``ambiguous-command``
   A command name resolved to multiple procedure candidates.

``unresolved-package``
   A ``package require`` target could not be found in builtin metadata or the
   discovered workspace/package roots.

``unresolved-variable``
   A procedure-scoped variable reference could not be resolved confidently.

``ambiguous-variable``
   A procedure-scoped variable reference matched multiple bindings.

Errors:

``duplicate-proc``
   The same qualified procedure name is declared multiple times in the active
   workspace.

Metadata-Driven Command Diagnostics
-----------------------------------

These rely on builtin or project metadata for command shape and option parsing.

``wrong-argument-count``
   The command call does not match any known arity for the resolved command.

``unknown-subcommand``
   The first positional argument does not match a known subcommand for the
   resolved command.

``unknown-option``
   An option-like argument does not match any declared metadata option for the
   resolved command.

``missing-option-value``
   A known metadata option that requires a value is missing that following
   value.

``invalid-regex``
   A statically known pattern for ``regexp`` or ``regsub`` fails Tcl regular
   expression compilation.

Practical Notes
---------------

The diagnostic set is intentionally conservative:

* dynamic Tcl patterns may suppress diagnostics instead of guessing
* metadata only drives checks when command resolution is confident enough
* some issues that would require runtime evaluation are intentionally not
  reported

For the best results:

* keep project metadata current
* add ``plugin-path`` or ``lib-path`` entries in ``tcllsrc.tcl`` when your
  project depends on custom DSLs or external package trees
* use ``uv run tcl-check --context-lines 2 path/to/project`` when you need the
  most readable terminal diagnostics

