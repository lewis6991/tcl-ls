Meta Syntax
===========

This page documents the current ``*.meta.tcl`` syntax accepted by ``tcl-ls``.
It uses the settled declaration names, clause shapes, and precedence rules for
metadata files.

File-Level Declarations
-----------------------

Metadata files use ordinary Tcl syntax, but ``tcl-ls`` only interprets a small
declarative subset. The accepted file-level forms are:

.. code-block:: tcl

   meta module name

   meta command name {shape}
   meta command name {shape} {
       clause ...
   }

   meta command name variants {
       form {shape}
       form {shape} {
           clause ...
       }
       command name {shape}
       command name {shape} {
           clause ...
       }
       command name variants {
           ...
       }
   }

   meta language languageName {
       command name {shape}
       command name {shape} {
           clause ...
       }
       command name variants {
           form {shape}
           form {shape} {
               clause ...
           }
           command name {shape}
           command name {shape} {
               clause ...
           }
           command name variants {
               ...
           }
       }
   }

Rules:

* declaration words must be static Tcl words
* command and language names must be a single word
* nested command names must be declared with ``command``, not with a spaced
  top-level name such as ``meta command {file atime} ...``
* leading ``#`` comments immediately before a ``meta command`` or nested
  ``command`` become documentation for hover and completion output

Minimal example:

.. code-block:: tcl

   # Tcl builtin command metadata for tcl-ls.
   meta module Tcl

   # Append to a variable.
   meta command append {varName args} {
       bind 1 append
   }

   meta language example-dsl {
       command method {name params body} {
           procedure {
               name select 1
               params select 2
               body select 3
           }
       }
   }

Override Precedence
-------------------

Metadata loading follows root precedence as well as per-file syntax. When more
than one metadata root is active, later roots override earlier ones.

Rules:

* later roots override earlier command trees by exact command name or prefix
* overriding ``namespace`` replaces earlier ``namespace`` and
  ``namespace ...`` metadata
* overriding ``namespace eval`` replaces earlier ``namespace eval`` and
  ``namespace eval ...`` metadata, but does not replace unrelated
  ``namespace export`` metadata
* within a single metadata root, conflicting declarations for the same command
  tree are treated as errors instead of order-dependent overrides
* a declaration with no clauses still counts as an override and clears earlier
  clauses for that command tree
* sibling ``foo.meta.tcl`` files are auto-associated with ``foo.tcl`` or
  ``foo.tm`` only when that match is unambiguous

This keeps override behavior deterministic. Project metadata can replace
bundled metadata cleanly, but ``tcl-ls`` does not try to guess between
multiple same-stem source siblings or merge conflicting declarations from one
root.

``meta module``
---------------

.. code-block:: tcl

   meta module Tcl

``meta module`` declares the builtin or package name represented by the file.
``tcl-ls`` uses it when grouping metadata by module or package name. A file can
still contain usable ``meta command`` and ``meta language`` declarations
without it, but module-aware builtin and package indexing depends on this
declaration.

Example module declarations from this repository:

.. code-block:: tcl

   meta module Tcl
   meta module TclOO
   meta module tepam

``meta command``, ``variants``, and ``form``
--------------------------------------------

``meta command`` declares either a single callable form directly or an
explicit ``variants`` block.

.. code-block:: tcl

   meta command regexp {args}
   meta command regexp {args} {
       option -all
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

   meta command after variants {
       form {ms}
       form {ms script args}
       form {idle script args}
       form {cancel idOrScript}
       form {info {id {}}}
   }

``name`` is the runtime command name or command prefix. It must be a single
word. ``shape`` is the structural description of one callable form. It is not
display-only text.

The single-form shorthand:

.. code-block:: tcl

   meta command append {varName args} {
       bind 1 append
   }

means the same thing as:

.. code-block:: tcl

   meta command append variants {
       form {varName args} {
           bind 1 append
       }
   }

Rules:

* the braced payload on ``meta command`` and ``form`` is the machine-read
  command shape
* single-form commands may use the shorthand form above
* commands that declare explicit ``form`` entries must use a ``variants`` block
* ``variants`` blocks must declare at least one ``form`` for the command node
  itself; nested ``command`` entries only add child nodes
* there is no separate ``usage`` clause

Example:

.. code-block:: tcl

   # Append all values to a variable.
   meta command append {varName args} {
       bind 1 append
   }

   # Model option-aware regexp bindings.
   meta command regexp {args} {
       option -all
       option -indices
       option -inline
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

``meta language``
-----------------

.. code-block:: tcl

   meta language tcloo-definition {
       command method {name args body} {
           procedure {
               name select 1
               params select 2
               body select 3
               language tcloo-method
           }
       }
   }

``meta language`` declares a named embedded command language. Inside the body,
each entry uses ``command`` rather than ``meta command``. Those nested
commands are only valid while a matching ``enter`` clause is active.

This splits the old overloaded ``context`` model into three separate jobs:

* ``meta language name { ... }`` declares a named embedded language
* ``enter language body selector ? owner selector ?`` activates that language
  for selected body words
* ``procedure { ... language name }`` selects the language used for a
  procedure-like body

Example:

.. code-block:: tcl

   meta command oo::define {className args} {
       enter tcloo-definition body 2.. owner 1
   }

   meta language tcloo-definition {
       command method {name args body} {
           procedure {
               name select 1
               params select 2
               body select 3
               language tcloo-method
           }
       }
   }

How ``meta language`` works:

* ``meta language`` only defines a named embedded language; it does not
  activate anything by itself
* a separate ``enter`` clause on some enclosing command decides when that
  language becomes active
* once active, commands inside the selected body are matched against the
  ``command`` entries declared in that language
* those nested commands can then use their own clauses such as ``procedure``,
  ``bind``, ``ref``, ``enter``, or another nested ``command``

Single script word vs inline command tail:

* if ``body`` selects one argument, that one word is parsed as an embedded Tcl
  script
* if ``body`` selects multiple contiguous arguments, ``tcl-ls`` treats that
  contiguous range as an inline embedded command stream

This is why both of these forms work:

.. code-block:: tcl

   meta command oo::class {subcommand args} {
       command create {className definitionScript} {
           enter tcloo-definition body 2 owner 1
       }
   }

   oo::class create ::Widget {
       method greet {name} {puts $name}
   }

.. code-block:: tcl

   meta command oo::define {className args} {
       enter tcloo-definition body 2.. owner 1
   }

   oo::define ::Widget method greet {name} {puts $name}

In the first form, the braced definition script is one selected body word. In
the second form, ``method greet {name} {puts $name}`` is a contiguous selected
tail of command words.

End-to-end example:

.. code-block:: tcl

   meta command oo::define {className args} {
       enter tcloo-definition body 2.. owner 1
   }

   meta language tcloo-definition {
       command method {name args body} {
           procedure {
               name select 1
               params select 2
               body select 3
               language tcloo-method
           }
       }
   }

   meta language tcloo-method {
       command my {methodName args} {
           command variable {name args} {
               bind 1.. variable
               ref 1..
           }
       }
   }

   oo::define ::Widget method greet {name} {
       my variable counter
       puts $name
   }

What ``tcl-ls`` derives from that:

* the ``enter`` clause sees ``oo::define`` and activates ``tcloo-definition``
* ``owner 1`` resolves to ``::Widget``
* ``body 2..`` selects the inline tail beginning at ``method``
* the language ``command method`` entry matches that embedded call
* the ``procedure`` clause creates a procedure-like declaration named
  ``greet`` with qualified name ``::Widget method greet``
* ``language tcloo-method`` then activates a second embedded language for the
  method body, so ``my variable counter`` is analyzed with the TclOO-specific
  metadata for ``my``

Selector Syntax
---------------

Many clauses select one or more runtime arguments. Selectors use this grammar:

.. code-block:: text

   selector ::= ["after-options"] ["list"] range ["step" N]
   range    ::= index | index ".." | index ".." index
   index    ::= positive-1-based-index | "last" | "last-N"

Selectors are used directly by clauses such as ``bind``, ``ref``, ``source``,
and ``enter``, and after ``select`` in multi-kind slots such as ``procedure``
and ``package``.

Examples:

* ``1`` selects the first argument
* ``3..`` selects the third argument through the end
* ``2..5`` selects arguments 2 through 5 inclusive
* ``last`` selects the final argument
* ``last-1`` selects the argument before the final one
* ``1..last-1`` selects everything except the final argument
* ``after-options 2`` selects the second positional argument after declared
  options are consumed
* ``list 2`` splits argument 2 as a Tcl list and selects each list item
* ``1..last-1 step 2`` selects every second argument in the chosen range

Selector rules:

* selector indexes are 1-based
* ``step N`` requires a range, not a single point
* ``after-options`` uses declared ``option`` clauses to skip known flags and
  flag values
* ``list`` changes the meaning from "selected word" to "selected Tcl-list
  element inside that word"
* selectors that depend on unstable argument expansion tails may be ignored
  conservatively during analysis

Selector examples in context:

.. code-block:: tcl

   # The first argument is a bound variable name.
   meta command append {varName args} {
       bind 1 append
   }

   # All arguments after the second one are Tcl bodies.
   meta command if {test body args} {
       enter tcl body 2..
   }

   # A foreach-style command can bind every second element of a list argument.
   meta command foreach {varList list args} {
       bind list 1..last-1 step 2 foreach
       enter tcl body last
   }

   # Skip known options before selecting positional captures.
   meta command regexp {args} {
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

Annotation Reference
--------------------

``option``
~~~~~~~~~~

.. code-block:: tcl

   option name
   option name value
   option -- stop

Declares known option parsing behavior for the enclosing command.

* ``option name`` declares a flag option with no value
* ``option name value`` declares an option that consumes one following value
* ``option -- stop`` declares ``--`` as the end of option parsing

Example:

.. code-block:: tcl

   meta command regexp {args} {
       option -all
       option -indices
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

Nested ``command``
~~~~~~~~~~~~~~~~~~

.. code-block:: tcl

   command name {shape}
   command name {shape} {
       clause ...
   }

   command name variants {
       form {shape}
       form {shape} {
           clause ...
       }
   }

Declares a nested command node using the same model as ``meta command``. The
command name must be a single word. Nested declarations also contribute child
command names to the parent command tree.

Example:

.. code-block:: tcl

   meta command array {subcommand args} {
       command exists {arrayName}
       command get {arrayName ?pattern?}
       command set {arrayName list}
   }

``bind``
~~~~~~~~

.. code-block:: tcl

   bind selector
   bind selector kind

Marks the selected argument or list elements as introduced variable bindings.
``kind`` is optional, but when present it must be one of:

``append``, ``array``, ``catch``, ``foreach``, ``gets``, ``global``, ``incr``,
``lappend``, ``lassign``, ``lmap``, ``parameter``, ``regexp``, ``regsub``,
``scan``, ``set``, ``switch``, ``upvar``, or ``variable``.

Examples:

.. code-block:: tcl

   meta command append {varName args} {
       bind 1 append
   }

   meta command foreach {varList list args} {
       bind list 1..last-1 step 2 foreach
       enter tcl body last
   }

``ref``
~~~~~~~

.. code-block:: tcl

   ref selector

Marks the selected argument or list elements as variable references.

Example:

.. code-block:: tcl

   meta language tcloo-method {
       command my {methodName args} {
           command variable {name args} {
               bind 1.. variable
               ref 1..
           }
       }
   }

``enter``
~~~~~~~~~

.. code-block:: tcl

   enter language body selector
   enter language body selector owner selector

Enters a named embedded language for one or more body arguments.

``language`` names a language declared with ``meta language``. ``body``
selects the word or words that should be reparsed using that language.
``owner`` is optional and names the entity that owns that embedded language
instance, which lets nested procedure-like declarations derive stable
qualified names and namespace anchors.

Rules:

* ``enter`` is a normal sibling clause inside a form
* multiple ``enter`` clauses may appear in the same form
* ``body`` accepts direct positional selectors, including contiguous ranges and
  ``after-options`` selectors, but not ``list`` selectors or stepped
  non-contiguous ranges
* ``owner`` must select exactly one direct argument; ``list`` and
  ``after-options`` selectors are not supported there
* when ``owner`` is present, the selected argument should still be static
* if multiple body arguments are selected, they must form one contiguous range

Behavior notes:

* one selected body argument means "parse this word as an embedded script"
* multiple selected body arguments mean "treat this contiguous range as an
  inline embedded command stream"
* overlapping body selections with different languages are conflicts

Examples:

.. code-block:: tcl

   meta command while {test body} {
       enter tcl body 2
   }

   meta command oo::define {className args} {
       enter tcloo-definition body 2.. owner 1
   }

   meta command wrapper {pkg script resultVar} {
       package select 1
       enter tcl body 2
       bind 3 set
   }

``source``
~~~~~~~~~~

.. code-block:: tcl

   source selector caller
   source selector definition

Treats the selected argument or arguments as source paths.

The final token chooses the resolution anchor:

* ``caller`` resolves relative to the file containing the call
* ``definition`` resolves relative to the file that declared the matched
  metadata-backed command

Unlike ``package``, ``source`` keeps the general selector model. One command
shape may name one source path, several source paths, or a list of source
paths.

Examples:

.. code-block:: tcl

   meta command source {fileName} {
       source 1 caller
   }

   meta command custom::loader {relativePath} {
       source 1 definition
   }

   meta command batch::source {paths} {
       source list 1 caller
   }

``package``
~~~~~~~~~~~

.. code-block:: tcl

   package literal TclOO
   package select 1

Records a package dependency.

This clause stays intentionally narrow: it records a package name dependency,
not the full surface of ``package require``.

Rules:

* ``package literal NAME`` records a fixed package dependency
* ``package select SELECTOR`` records a dependency whose package name comes
  from one runtime argument
* package selectors must resolve to exactly one non-list argument
* ``literal`` and ``select`` are explicit because names such as ``select`` are
  valid package names

Examples:

.. code-block:: tcl

   meta command package::ifneeded-wrapper {name version script} {
       package select 1
       enter tcl body 3
   }

   meta command use-tcloo {args} {
       package literal TclOO
   }

``procedure``
~~~~~~~~~~~~~

.. code-block:: tcl

   procedure {
       name select selector
       params select selector
       body select selector
       language body-language
   }

Describes a procedure-like declaration emitted by the enclosing command.

``procedure`` remains block-shaped because it is genuinely a small record.

Rules:

* ``name`` is required and accepts ``select SELECTOR``, ``literal VALUE``, or
  ``-``
* ``params`` is required and accepts ``select SELECTOR``, ``literal VALUE``, or
  ``-``
* ``body`` is optional and, when present, uses ``select SELECTOR``
* ``language`` is optional and names the embedded language used for the body
* ``language`` may only appear when ``body`` is also present
* selector-valued fields use the general selector language, not a special
  positive-index-only syntax

Examples:

.. code-block:: tcl

   command method {name args body} {
       procedure {
           name select 1
           params select 2
           body select 3
           language tcloo-method
       }
   }

   command constructor {args body} {
       procedure {
           name -
           params select 1
           body select 2
           language tcloo-method
       }
   }

   command destructor {body} {
       procedure {
           name -
           params -
           body select 1
           language tcloo-method
       }
   }

   command declare {name params} {
       procedure {
           name select 1
           params select 2
       }
   }

``plugin``
~~~~~~~~~~

.. code-block:: tcl

   plugin scriptPath procName

Calls a Tcl-side plugin hook for matching command instances.

Rules:

* ``scriptPath`` is resolved relative to the metadata file when it is not
  absolute
* the referenced script must exist when the metadata is loaded
* the procedure is invoked as ``procName words info``
* plugin results should reuse ordinary metadata effect shapes rather than
  inventing a second metadata language

Example:

.. code-block:: tcl

   meta command tepam::procedure {name attributes body} {
       plugin tepam.tcl ::tcl_lsp::plugins::tepam::statementWords
   }

Plugin Return Format
--------------------

A plugin returns a Tcl list of effects. Effects should reuse the declarative
metadata surface as much as possible.

The current target effect shape is:

.. code-block:: tcl

   procedure {
       name select 1
       params literal {left right}
       _params-source select 2
       body select 3
       language sample
   }

Effect rules:

* plugin ``procedure`` effects should use the same field names and value kinds
  as declarative ``procedure`` clauses
* plugin positions are 1-based, not separate zero-based ``*-index`` fields
* ``_params-source`` is a provisional escape hatch for plugin-derived literal
  parameters whose source location still needs a coarse word anchor
* ``_params-source`` is intentionally separate from ``params`` so it can be
  removed or replaced later without locking the core ``procedure`` syntax into
  a hack

Example plugin return:

.. code-block:: tcl

   return [list [list procedure {
       name select 1
       params literal {left right}
       _params-source select 2
       body select 3
       language sample
   }]]

The plugin host runs each call in a fresh safe Tcl interpreter, so plugins do
not share state between invocations and do not have access to unsafe Tcl
commands such as unrestricted I/O or package loading.
