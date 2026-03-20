Meta Syntax
===========

This page documents the ``*.meta.tcl`` syntax that ``tcl-ls`` accepts when it
loads metadata files.

File-Level Declarations
-----------------------

Metadata files use ordinary Tcl syntax, but ``tcl-ls`` only interprets a small
declarative subset. The accepted file-level forms are:

.. code-block:: tcl

   meta module name
   meta command name {signature}
   meta command name {signature} {
       annotation ...
   }
   meta context contextName {
       command name {signature}
       command name {signature} {
           annotation ...
       }
   }

Rules:

* declaration words must be static Tcl words
* command names must be a single word
* nested command names must be declared with ``subcommand``, not with a spaced
  top-level name such as ``meta command {file atime} ...``
* leading ``#`` comments immediately before a ``meta command``, ``subcommand``,
  or context ``command`` become documentation for hover and completion output

Minimal example:

.. code-block:: tcl

   # Tcl builtin command metadata for tcl-ls.
   meta module Tcl

   # Append to variable.
   meta command append {varName args} {
       bind 1
   }

   meta context example-dsl {
       command method {name params body} {
           procedure {
               name 1
               params 2
               body 3
           }
       }
   }

``meta module``
---------------

.. code-block:: tcl

   meta module Tcl

``meta module`` declares the builtin or package name represented by the file.
``tcl-ls`` uses it when grouping metadata by module or package name. A file can
still contain usable ``meta command`` and ``meta context`` declarations without
it, but module-aware builtin/package indexing depends on this declaration.

Example module declarations from this repository:

.. code-block:: tcl

   meta module Tcl
   meta module TclOO
   meta module tepam

``meta command``
----------------

.. code-block:: tcl

   meta command regexp {args}
   meta command regexp {args} {
       option -all
       option -start value
       option -- stop
       bind after-options 3..
   }

``name`` is the runtime command name or command prefix. It must be a single
word. ``signature`` is static text shown in hover and completion details. The
annotation body is optional and, when present, must be a static Tcl command
list.

Example:

.. code-block:: tcl

   # Append all values to a variable.
   meta command append {varName args} {
       bind 1
   }

   # Model option-aware variable bindings.
   meta command regexp {args} {
       option -all
       option -indices
       option -inline
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

``meta context``
----------------

.. code-block:: tcl

   meta context tcloo-definition {
       command method {name params body} {
           procedure {
               name 1
               params 2
               body 3
               context tcloo-method
           }
       }
   }

``meta context`` declares an embedded command language. Inside the body, each
entry uses ``command`` rather than ``meta command``. Those nested commands are
only valid while a matching ``context`` annotation is active.

Example:

.. code-block:: tcl

   meta command oo::define {className args} {
       context tcloo-definition {
           body 2..
           owner 1
       }
   }

   meta context tcloo-definition {
       command method {name args body} {
           procedure {
               name 1
               params 2
               body 3
               context tcloo-method
           }
       }
   }

How ``meta context`` actually works:

* ``meta context`` only defines a named embedded language; it does not activate
  anything by itself
* a separate ``context`` annotation on some enclosing command decides when that
  language becomes active
* once active, commands inside the selected body are matched against the
  ``command`` entries declared in that named context
* those nested commands can then use their own annotations such as
  ``procedure``, ``bind``, ``ref``, ``script-body``, or even another
  ``context``

Think of it as a two-step model:

1. ``meta context name { ... }`` declares the vocabulary of an embedded DSL.
2. ``context name { body ...; owner ... }`` tells ``tcl-ls`` where that DSL is
   used in real Tcl code.

What ``owner`` does:

* ``owner`` selects the command argument that names the thing being defined,
  such as a class, object, widget, or namespace-qualified DSL owner
* the owner must be statically known or ``tcl-ls`` will skip entering that
  context
* the selected owner name is qualified relative to the current namespace
* nested ``procedure`` annotations use that owner name to build stable
  qualified names for declarations found inside the context

For TclOO, this means a method declared inside ``oo::define Widget ...`` is
anchored to ``Widget`` rather than being treated like an unrelated global
procedure.

Single script word vs inline command tail:

* if ``body`` selects one argument, that one word is parsed as an embedded Tcl
  script
* if ``body`` selects multiple contiguous arguments, ``tcl-ls`` treats that
  contiguous tail as an inline embedded command stream

This is why both of these forms work:

.. code-block:: tcl

   meta command oo::class {subcommand args} {
       subcommand create {className definitionScript} {
           context tcloo-definition {
               body 2
               owner 1
           }
       }
   }

   oo::class create ::Widget {
       method greet {name} {puts $name}
   }

.. code-block:: tcl

   meta command oo::define {className args} {
       context tcloo-definition {
           body 2..
           owner 1
       }
   }

   oo::define ::Widget method greet {name} {puts $name}

In the first form, the braced definition script is one selected body word. In
the second form, ``method greet {name} {puts $name}`` is a contiguous selected
tail of command words.

End-to-end example:

.. code-block:: tcl

   meta command oo::define {className args} {
       context tcloo-definition {
           body 2..
           owner 1
       }
   }

   meta context tcloo-definition {
       command method {name args body} {
           procedure {
               name 1
               params 2
               body 3
               context tcloo-method
           }
       }
   }

   meta context tcloo-method {
       command my {methodName args}
   }

   oo::define ::Widget method greet {name} {
       my variable counter
       puts $name
   }

What ``tcl-ls`` derives from that:

* the ``context`` annotation sees ``oo::define`` and activates
  ``tcloo-definition``
* ``owner 1`` resolves to ``::Widget``
* ``body 2..`` selects the inline tail beginning at ``method``
* the contextual ``method`` command matches the ``meta context`` entry
* the ``procedure`` annotation creates a procedure-like declaration named
  ``greet`` with qualified name ``::Widget method greet``
* ``context tcloo-method`` then activates a second embedded language for the
  method body, so ``my variable counter`` is analyzed with the TclOO-specific
  metadata for ``my``

Selector Syntax
---------------

Many annotations select one or more runtime arguments. Selectors use this
grammar:

.. code-block:: text

   selector ::= ["after-options"] ["list"] range ["step" N]
   range    ::= index | index ".." | index ".." index
   index    ::= positive-1-based-index | "last" | "last-N"

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
* ``after-options`` uses declared ``option`` annotations to skip known flags
  and flag values
* ``list`` changes the meaning from "selected word" to "selected Tcl-list
  element inside that word"
* selectors that depend on unstable argument expansion tails may be ignored
  conservatively during analysis

Selector examples in context:

.. code-block:: tcl

   # The first argument is a bound variable name.
   meta command append {varName args} {
       bind 1
   }

   # All arguments after the second one are bodies.
   meta command if {test body args} {
       script-body 2..
   }

   # A foreach-style command can bind every second element of a list argument.
   meta command foreach {varList list args} {
       bind list 1..last-1 step 2 foreach
       script-body last
   }

   # Skip known options before selecting positional captures.
   meta command regexp {args} {
       option -start value
       option -- stop
       bind after-options 3..
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
       bind after-options 3..
   }

``subcommand``
~~~~~~~~~~~~~~

.. code-block:: tcl

   subcommand name {signature}
   subcommand name {signature} {
       annotation ...
   }

Declares a nested subcommand using the same shape as ``meta command``. The
subcommand name must be a single word. Nested declarations also contribute
derived subcommand names to the parent command.

Example:

.. code-block:: tcl

   meta command array {subcommand args} {
       subcommand exists {arrayName}
       subcommand get {arrayName ?pattern?}
       subcommand set {arrayName list}
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
       script-body last
   }

``ref``
~~~~~~~

.. code-block:: tcl

   ref selector

Marks the selected argument or list elements as variable references.

Example:

.. code-block:: tcl

   meta context tcloo-method {
       command my {methodName args} {
           subcommand variable {name args} {
               bind 1.. variable
               ref 1..
           }
       }
   }

``script-body``
~~~~~~~~~~~~~~~

.. code-block:: tcl

   script-body selector

Treats the selected argument or arguments as embedded Tcl script bodies and
reparses them for nested analysis.

Example:

.. code-block:: tcl

   meta command while {test body} {
       script-body 2
   }

``source``
~~~~~~~~~~

.. code-block:: tcl

   source selector call-source-directory
   source selector proc-source-parent

Treats the selected argument as a source path. The base directory must be one
of:

* ``call-source-directory`` to resolve relative to the file containing the call
* ``proc-source-parent`` to resolve relative to the file that declared the
  matched metadata-backed procedure

Examples:

.. code-block:: tcl

   meta command source {fileName} {
       source 1 call-source-directory
   }

   meta command custom::loader {relativePath} {
       source 1 proc-source-parent
   }

``package``
~~~~~~~~~~~

.. code-block:: tcl

   package TclOO
   package 1

Records a package dependency.

* ``package name`` records a fixed literal dependency
* ``package selector`` records a dependency whose package name comes from one
  runtime argument

Package selectors must resolve to exactly one non-list argument.

Examples:

.. code-block:: tcl

   meta command package::ifneeded-wrapper {name version script} {
       package 1
       script-body 3
   }

   meta command use-tcloo {args} {
       package TclOO
   }

``context``
~~~~~~~~~~~

.. code-block:: tcl

   context context-name {
       body selector
       owner selector
   }

Enters a named embedded command language for one or more body arguments.
``owner`` names the entity that owns that embedded context instance, which lets
procedure-like nested declarations derive stable qualified names and namespace
anchors.

This annotation activates a language previously declared with
``meta context``. The declaration defines the available nested commands; the
annotation tells ``tcl-ls`` which argument or arguments should be analyzed
using that language.

Restrictions:

* ``body`` and ``owner`` are both required
* both selectors must be direct positional selectors
* ``owner`` must resolve to exactly one argument
* ``list`` and ``after-options`` are not allowed here
* the selected owner name must be static
* if multiple body arguments are selected, they must form one contiguous range

Behavior notes:

* one selected body argument means "parse this word as an embedded script"
* multiple selected body arguments mean "treat this contiguous tail as an
  inline contextual command stream"
* the owner name becomes the namespace anchor for nested procedure-like
  declarations found inside the context

Example:

.. code-block:: tcl

   meta command oo::define {className args} {
       context tcloo-definition {
           body 2..
           owner 1
       }
   }

``procedure``
~~~~~~~~~~~~~

.. code-block:: tcl

   procedure {
       name index|-
       params index|-
       body index
       context body-context
   }

Describes a procedure-like declaration emitted by the enclosing command.

Rules:

* ``name`` is required and selects the declared member name, or ``-`` when the
  command has no separate member name
* ``params`` is required and selects the formal Tcl parameter list, or ``-``
  when there is none
* ``body`` is required and selects the script body
* ``context`` is optional and selects the embedded language used for the body
* these indexes are positive 1-based argument positions, not general selectors

Examples:

.. code-block:: tcl

   command method {name args body} {
       procedure {
           name 1
           params 2
           body 3
           context tcloo-method
       }
   }

   command destructor {body} {
       procedure {
           name -
           params -
           body 1
           context tcloo-method
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

The ``info`` dict currently contains:

* ``embedded-language``
* ``embedded-owner-name``
* ``metadata-command``
* ``namespace``
* ``prefix-word-count``
* ``procedure-symbol-id``
* ``scope-id``
* ``static-flags``
* ``expanded-flags``
* ``uri``

Example:

.. code-block:: tcl

   meta command tepam::procedure {name attributes body} {
       plugin tepam.tcl ::tcl_lsp::plugins::tepam::statementWords
   }

Plugin Return Format
--------------------

A plugin returns a Tcl list of effects. The currently supported effect is
``procedure``:

.. code-block:: tcl

   procedure {
       name-index N
       params-word-index N
       params {name ...}
       body-index N
       context body-context
   }

Effect rules:

* ``name-index`` is required and is a zero-based word index into the full
  command word list seen by the plugin
* ``params`` is required and is the parameter-name list to attach to the
  declared procedure
* ``params-word-index`` is optional and points at the source word that declared
  the parameters
* ``body-index`` is optional for declaration-only effects
* ``context`` is optional and selects the embedded language for the procedure
  body

Example plugin return:

.. code-block:: tcl

   set effect [dict create
       name-index 1
       params-word-index 2
       params {left right}
       body-index 3
       context sample
   ]
   return [list [list procedure $effect]]

The plugin host runs each call in a fresh safe Tcl interpreter, so plugins do
not share state between invocations and do not have access to unsafe Tcl
commands such as unrestricted I/O or package loading.
