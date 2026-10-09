Metadata Syntax
===============

Metadata uses Tcl syntax with a static declaration language. Names, paths,
shapes, and annotation words must be static; metadata loading does not execute
Tcl commands. For an authoring workflow, see :doc:`../meta`.

.. _metadata-composition:

Modules And Includes
--------------------

.. code-block:: tcl

   source path
   meta module name {body}
   meta module name -environment {body}

``meta module`` groups declarations for Tcl, a package, or a tool environment.
The body must be a braced command block. A file can contain several modules.
Nested module blocks select their own module and restore the outer module
when they end.

``source`` includes exactly one file at that position. Paths are relative to
the file containing the include. Included declarations inherit the enclosing
module unless they select another one. This allows a fragment to be shared
between modules. Missing files, dynamic paths, and include cycles are errors.

.. code-block:: tcl

   meta module Tcl {
       source common.meta.tcl
       meta command project_command {value}
   }
   meta module JasperGold -environment {
       source jasper.meta.tcl
       meta override clock {args}
   }

The ``Tcl`` module supplies commands available by default. Package modules
describe package commands. A module with ``-environment`` contributes commands
only where that environment is selected; neither ``package require`` nor a
qualified command name activates it. See :ref:`tool-environments` for
environment selection.

Declarations outside a module are file-scoped. ``foo.meta.tcl`` is associated
with ``foo.tcl`` or ``foo.tm`` when that match is unambiguous. If neither
source sibling exists beside the metadata, the default association is
``foo.tcl``. File-scoped declarations from different files remain separate.

.. _metadata-precedence:

Precedence
~~~~~~~~~~

Metadata roots are loaded in order: bundled metadata, project configuration
from parent to child directories, then checker ``--meta-path`` arguments.
Later roots replace earlier command trees with the same module and language.
Within one root, explicit includes and module blocks follow declaration order;
later blocks replace earlier command trees.

* Replacing ``namespace`` removes earlier metadata for ``namespace`` and all
  its subcommands.
* Replacing the nested command ``namespace eval`` removes that branch only;
  ``namespace export`` remains.
* A declaration without annotations still replaces earlier annotations.
* Overloads declared together are retained.
* Independent files discovered in a directory cannot declare the same command
  in the same module. An included file is loaded through its includes, not
  also as an independent file.
* Repeated ``meta language`` blocks compose within one root. A later root
  replaces the language's ``extends tcl`` policy.

These rules govern metadata for the same module. Replacing a command from Tcl
or a lower active environment is a separate operation: use ``meta override``
as described below.

Aliases And Overrides
---------------------

.. code-block:: tcl

   meta alias name target
   meta alias name target -module moduleName
   meta override name {shape}

Both declarations require a module block.

``meta alias`` reuses the target's signatures, subcommands, documentation, and
annotations. Targets resolve in the same module after metadata precedence is
applied. Use ``-module`` to select another module. Alias chains are supported;
missing targets and cycles are errors. The declaration describes an alias or
renamed command provided by the program; it leaves the target metadata in place.

``meta override`` accepts the same shapes, annotations, and variants as
``meta command``. In an environment, it replaces a command tree from Tcl or a
lower environment. Ordinary environment commands only add names that are not
already present.

.. code-block:: tcl

   meta module JasperGold -environment {
       meta override clock {args}
       meta alias tcl_clock clock -module Tcl
   }

Fixed Source Dependencies
-------------------------

.. code-block:: tcl

   meta source path

``meta source`` records a dependency of the associated Tcl file. It is allowed
only outside module blocks. For example, ``loader.meta.tcl`` can contain:

.. code-block:: tcl

   meta source ../src/common.tcl

The analyzer then reads that dependency when it reads ``loader.tcl``. Paths
are relative to the metadata file. Later metadata roots replace earlier source
lists for the same associated filename.

Use ordinary ``source path`` to include metadata. To describe a command whose
arguments select source files, use the :ref:`source annotation
<metadata-source-annotation>`.

Commands And Variants
---------------------

.. code-block:: tcl

   meta command name {shape}
   meta command name {shape} {
       clause ...
   }
   meta command name variants {
       form {shape}
       form {shape} {
           clause ...
       }
       command childName {shape}
   }

``name`` is a single word, optionally namespace-qualified. Use nested
``command`` declarations for subcommands rather than a spaced name such as
``meta command {file atime}``.

The shape describes accepted arguments and is used for call checking. A direct
shape is shorthand for one ``form`` in a ``variants`` block. Explicit ``form``
entries require ``variants``, and each variants block must contain at least
one form for its own command. Nested commands do not satisfy that requirement.

Place ``-visibility public|internal`` between the name and shape (or
``variants``). Visibility defaults to ``public`` and applies to all forms of
that command. Nested commands have their own visibility; aliases inherit the
target's visibility. Repeated declarations of the same command in one block
must agree. ``meta override`` and embedded-language commands accept the same
option.

.. code-block:: tcl

   meta command prove {args}
   meta command _set_property -visibility internal {args}

Hover text labels internal commands and omits public visibility. Internal
command calls use the standard ``deprecated`` semantic-token modifier so
editors apply their existing deprecated style. Visibility does not restrict
calls. Public commands keep their normal highlighting.

Leading ``#`` comments immediately before a command declaration become its
hover and completion documentation.

.. code-block:: text

   # Append all values to a variable.
   meta command append {varName args} {
       bind 1 append
   }

   meta command after variants {
       form {ms}
       form {ms script args}
       form {=idle script args}
       form {=cancel idOrScript}
       form {=info {id {}}}
   }

Command Shapes
~~~~~~~~~~~~~~

A command shape is a Tcl list. Each item describes an argument position:

* A plain word such as ``varName`` is a descriptive placeholder for one
  argument.
* Standalone ``?`` items enclose an optional group. ``? value ?`` permits one
  omitted argument; ``? option value ?`` makes the pair optional together.
* ``args`` consumes the remaining arguments and must be the final item.
* A word prefixed with ``=`` is a required literal: ``=select`` matches
  ``select``.
* ``{name default}`` describes one optional argument using Tcl parameter-list
  notation. The grouped item occupies one position, not two.

Signature help may display a defaulted argument as ``? name ?``. This is the
same optional argument, not a different shape.

The bundled ``meta.meta.tcl`` uses angle-bracket slots such as ``<name>`` and
``<selector>`` to describe metadata syntax itself. Use ordinary placeholders
for application command shapes.

Nested Commands
~~~~~~~~~~~~~~~

``command`` declares a child using the same shape, annotations, and variants
forms as ``meta command``. Each child contributes its name to the parent's
subcommand completion list.

.. code-block:: tcl

   meta command array {subcommand args} {
       command exists {arrayName}
       command get {arrayName ? pattern ?}
       command set {arrayName list}
   }

.. _metadata-languages:

Embedded Languages
------------------

.. code-block:: tcl

   meta language languageName {
       command name {shape} {
           clause ...
       }
   }

``meta language`` defines commands for an embedded language. The language name
must be one word. Entries use ``command`` instead of ``meta command`` and
support the same forms and annotations. Defining a language does not activate
it: an :ref:`enter <metadata-enter>` annotation or a
:ref:`procedure <metadata-procedures>` body selects it.

Languages are closed by default: only their declared commands are valid.
Add ``extends tcl`` once in the language body to allow ordinary Tcl commands
after its explicit entries are checked. ``tcl`` is the only supported target.
In an environment module, use ``override`` instead of ``command`` to replace
an embedded-language command from a lower environment.

This example models both a braced class definition and an inline method
declaration:

.. code-block:: tcl

   meta command oo::class {subcommand args} {
       command create {className definitionScript} {
           enter tcloo-definition body 2 owner 1
       }
   }
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
       extends tcl
       command my {methodName args} {
           command variable {name args} {
               bind 1.. variable
               ref 1..
           }
       }
       command next {args}
       command self {args}
   }

The metadata supports these source forms:

.. code-block:: tcl

   oo::class create ::Widget {
       method greet {name} {puts $name}
   }
   oo::define ::Widget method count {} {
       my variable counter
       incr counter
   }

``owner 1`` identifies ``::Widget``. ``enter`` reads one selected word as a
script, or a contiguous argument tail as an inline command. The ``method``
annotation creates a declaration such as ``::Widget method count`` and selects
``tcloo-method`` for its body. That language adds ``my`` while retaining Tcl
commands such as ``incr``.

.. _metadata-selectors:

Selectors
---------

Selectors identify runtime arguments after the matched command prefix. They
are 1-based: for ``array get``, argument 1 is the array name. Plugin effects
use a different base, described in :ref:`metadata-plugins`.

.. code-block:: text

   selector ::= ["after-options"] ["list"] range ["step" N]
   range    ::= index | index ".." | index ".." index
   index    ::= positive-1-based-index | "last" | "last-N"

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Selector
     - Selection
   * - ``1``
     - First argument
   * - ``3..``
     - Third argument through the end
   * - ``2..5``
     - Arguments 2 through 5, inclusive
   * - ``last``
     - Final argument
   * - ``last-1``
     - Argument before the final one
   * - ``1..last-1``
     - All arguments except the final one
   * - ``after-options 2``
     - Second positional argument after declared options and values are consumed
   * - ``list 2``
     - Each Tcl list element in argument 2
   * - ``1..last-1 step 2``
     - Every second argument in the range

``step N`` requires a range and a positive step. ``after-options`` relies on
the command's ``option`` annotations. ``list`` splits each selected word as a
Tcl list. Analysis may ignore selections that depend on an unknown argument
expansion.

Use selectors directly in ``bind``, ``ref``, ``source``, and ``enter``. In
fields that also accept a literal value, such as ``package`` and ``procedure``,
introduce the selector with ``select``. Each annotation can impose further
restrictions.

Annotations
-----------

``option``
~~~~~~~~~~

.. code-block:: tcl

   option name
   option name value
   option -- stop

The first form declares a flag without a value. The second consumes one value.
The third makes ``--`` end option parsing.

.. code-block:: tcl

   meta command regexp {args} {
       option -all
       option -indices
       option -inline
       option -start value
       option -- stop
       bind after-options 3.. regexp
   }

``bind`` And ``ref``
~~~~~~~~~~~~~~~~~~~~

.. code-block:: tcl

   bind selector
   bind selector kind
   ref selector

``bind`` records variable bindings from selected arguments or list elements.
Its optional ``kind`` identifies the binding behavior and must be one of:

``append``, ``array``, ``catch``, ``foreach``, ``gets``, ``global``, ``incr``,
``lappend``, ``lassign``, ``lmap``, ``parameter``, ``regexp``, ``regsub``,
``scan``, ``set``, ``switch``, ``upvar``, or ``variable``.

``ref`` records variable references. A command can use both annotations, as
``my variable`` does in the :ref:`embedded-language example
<metadata-languages>`.

.. code-block:: tcl

   meta command foreach {varList list args} {
       bind list 1..last-1 step 2 foreach
       enter tcl body last
   }

Here, every second argument before the final body is a list of variable names.

.. _metadata-enter:

``enter``
~~~~~~~~~

.. code-block:: tcl

   enter language body selector
   enter language body selector owner selector

Selects an embedded language for body arguments. ``tcl`` parses ordinary Tcl;
other names refer to ``meta language`` declarations. One selected word is
parsed as a script. Multiple selected words form an inline command stream and
must be contiguous.

``owner`` identifies the entity that owns the language instance. It lets
nested procedure declarations derive qualified names and namespace anchors.
The owner must be one static, direct argument; ``list`` and ``after-options``
are not allowed.

Body selectors can use ``after-options`` and contiguous ranges, but cannot use
``list`` or non-contiguous steps. Multiple ``enter`` annotations are allowed;
overlapping body selections are errors.

Commands that the analyzer handles structurally (``proc``, ``namespace eval``,
``for``, ``if``, ``catch``, ``try``, ``switch``, and ``while``) accept only
single-word selections of their existing script bodies. Use separate
annotations for separate bodies. Inline tails are supported for generic
commands.

.. code-block:: tcl

   meta command while {test body} {
       enter tcl body 2
   }
   meta command dsl::eval {context args} {
       enter tcl body 2..
   }

.. _metadata-source-annotation:

``source``
~~~~~~~~~~

.. code-block:: tcl

   source selector caller
   source selector definition

Records source paths selected from a call to a procedure with file-scoped
metadata. Each selected argument is one path. ``caller`` resolves relative
paths from the file containing the call. ``definition`` uses the parent of the
directory containing the procedure's Tcl file: for ``devtools/helpers.tcl``,
the base is the directory containing ``devtools``.

.. code-block:: tcl

   meta command custom::source {fileName} {
       source 1 caller
   }
   meta command custom::loader {relativePath} {
       source 1 definition
   }

Plugin source effects also support list selectors and use a different
``definition`` base; see :ref:`metadata-plugins`.

``package``
~~~~~~~~~~~

.. code-block:: tcl

   package literal packageName
   package select selector

Records a package-name dependency. ``literal`` supplies a fixed name;
``select`` reads one argument. Package selectors must select exactly one
non-list argument.

.. code-block:: tcl

   meta command package::ifneeded-wrapper {name version script} {
       package select 1
       enter tcl body 3
   }
   meta command use-tcloo {args} {
       package literal TclOO
   }

.. _metadata-procedures:

``procedure``
~~~~~~~~~~~~~

.. code-block:: tcl

   procedure {
       name select selector
       params select selector
       body select selector
       language body-language
   }

Describes a procedure declaration made by the enclosing command. ``name`` and
``params`` are required; ``body`` and ``language`` are optional. Each field
may appear only once, and ``language`` requires ``body``.

.. list-table::
   :header-rows: 1
   :widths: 20 45 35

   * - Field
     - Accepted forms
     - Meaning
   * - ``name``
     - ``select selector``, ``literal name``, ``-``
     - Declared name; ``-`` uses the enclosing command name tail
   * - ``params``
     - ``select selector``, ``select selector format formatName``,
       ``literal parameterList``, ``-``
     - Parameter definitions; ``-`` means no parameters
   * - ``body``
     - ``select selector``
     - Procedure body
   * - ``language``
     - Language name
     - Embedded language for the body

Each selector must identify exactly one non-list argument. Parameter lists
use Tcl procedure syntax: names, ``{name default}`` entries, and optional
trailing ``args``. ``params literal`` uses this syntax directly, not command
shape syntax.

``params select ... format`` supports:

* ``tcl``: ordinary Tcl parameter lists (the default).
* ``tepam``: a Tepam attribute list containing ``-args``.
* ``tepam-args``: the argument definitions from ``-args``, or a list of names.

The Tepam formats bind body variables and preserve each name's source location.
They remove a leading ``-`` from option names and read static lists without
evaluating defaults. They leave call arity unknown because body variables do
not describe Tepam's option-based call syntax.

The :ref:`embedded-language example <metadata-languages>` shows a method
declaration. These forms cover constructors, destructors, declarations without
bodies, and Tepam procedures:

.. code-block:: tcl

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
   command tepam::procedure {name attributes body} {
       procedure {
           name select 1
           params select 2 format tepam
           body select 3
       }
   }

.. _metadata-plugins:

Tcl Plugins
-----------

.. code-block:: tcl

   meta command project::declare {name attributes body} {
       plugin declare.tcl ::project::metadata::declare
   }

``plugin scriptPath procName`` calls a Tcl hook for each matching command.
Relative script paths resolve from the metadata file, and the script must
exist when metadata is loaded. The host requires ``tclsh`` on ``PATH``.

Plugin Inputs
~~~~~~~~~~~~~

The hook is invoked as ``procName words info``. ``words`` is a Tcl list for the
full source command, including its command name and subcommands. Static words
contain their text; dynamic words contain an empty string. Check
``static-flags`` to distinguish dynamic words from literal empty strings.

``info`` is a Tcl dictionary:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Key
     - Value
   * - ``static-flags``
     - One ``1`` or ``0`` per word, indicating whether its text is static
   * - ``expanded-flags``
     - One ``1`` or ``0`` per word, indicating ``{*}`` expansion
   * - ``metadata-command``
     - Matched metadata command name, or the target name for a metadata alias
   * - ``prefix-word-count``
     - Number of words in the matched command prefix
   * - ``namespace``
     - Current namespace
   * - ``embedded-language``
     - Current embedded language, or an empty string
   * - ``embedded-owner-name``
     - Current embedded owner, or an empty string
   * - ``uri``
     - Source document URI

The dictionary also carries opaque ``scope-id`` and ``procedure-symbol-id``
values. The procedure ID is empty outside a procedure.

Plugin Effects
~~~~~~~~~~~~~~

A plugin returns a Tcl list of effect clauses using the annotation forms
above. It may return ``bind``, ``ref``, ``enter``, ``package``, ``source``, and
``procedure``. It cannot return declarations such as ``command``, ``variants``,
``form``, ``option``, or ``plugin``.

Plugin selectors are 1-based over the full ``words`` list: selector 1 is the
command name. They do not support ``after-options``. Plugin ``bind`` effects
require an explicit kind. Procedure parameter formats and field restrictions
are the same as for declarative annotations.

For plugin ``source`` effects, ``caller`` resolves paths from the calling
file, while ``definition`` resolves them from the metadata file. List selectors
are supported: ``{source list 2 caller}`` reads paths from the first argument.

For a call shaped as ``declare name attributes body``, a plugin can return:

.. code-block:: tcl

   return {
       {procedure {
           name select 2
           params select 3 format tepam
           body select 4
       }}
   }

The optional plugin field ``_params-source select selector`` anchors literal
parameters to one source word. Prefer ``params select`` with a parameter format
when possible to preserve individual parameter locations.

Each call runs in a fresh safe Tcl interpreter. Plugins do not share state
between calls and cannot perform unrestricted I/O or package loading.
