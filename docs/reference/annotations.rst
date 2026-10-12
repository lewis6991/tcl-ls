Comment Annotations
===================

Use annotations in Tcl comments to describe procedure parameters, return
values, and effects. Both ``# @param`` and ``## @param`` comment forms are
supported, including descriptions continued on the following comment line.
The syntax follows the ``@param``, ``@return``, and
``@alias`` forms used by `LuaCATS
<https://luals.github.io/wiki/annotations/>`_, with Tcl list and dictionary
types.

.. code-block:: tcl

   namespace eval properties {
       # @alias State "enabled"|"disabled"
       # @alias Snapshot dict<string, {state: State, names: string[]}>

       # Update selected properties.
       # @param actual Snapshot State before conversion.
       # @param bound integer|"" Conversion bound.
       #              An empty string means no bound.
       # @return [Snapshot, string[]] Updated state and changed names.
       # @effects Reads tool state and can change properties.
       proc update {actual {bound {}}} {
           return [list $actual {}]
       }
   }

Hover, command completion, and signature help show the parameter and return
types. Signature help also shows the active parameter's description. Hover
on an alias declaration shows its definition. Procedure documentation includes
the aliases used by its types, including aliases used by other aliases.

Annotations do not change Tcl execution or argument counts. The server uses
parameter, return, and variable types in analysis, as described below. It does not yet
report type mismatches.

Annotation Forms
----------------

``# @param name type [description]``
   Describe a parameter by its name in the procedure declaration. The order
   of annotations does not change the order of parameters in the signature.

``# @return type [description]``
   Describe the procedure's single Tcl result. Use a tuple type to describe
   a list with a fixed sequence of elements. Use ``void`` when callers should
   ignore the result.

``# @effects description``
   Describe reads, writes, tool queries, or other effects. This text is for
   documentation; the server does not verify effects.

``# @type type [description]``
   Describe the value assigned by the next ``set name value`` command.
   Put the annotation in the comment block immediately before that command.
   It does not create a variable or apply to other commands.

``# @alias name type [description]``
   Give a type a name within the current Tcl namespace and source file.
   Alias lookup uses that namespace, then the global namespace. Aliases can
   refer to each other. Each referenced alias is shown once, including when
   aliases form a cycle. If a name is declared more than once in a namespace,
   the last declaration supplies its definition.

Place procedure annotations in the comment block immediately before the
declaration. A blank source line ends the block. An empty comment line, ``#``,
keeps it together. Indent a continuation line to extend an annotation's
description. These rules also apply to procedures recognized through metadata
or plugins.

Type Syntax
-----------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Form
     - Example
   * - Named type
     - ``string``, ``integer``, ``boolean``, ``dict``, ``Snapshot``
   * - Literal value
     - ``"enabled"``, ``'disabled'``, ``0``
   * - Union
     - ``integer | ""``
   * - List elements
     - ``string[]``, ``(string | integer)[]``
   * - Dictionary
     - ``dict<string, State>``
   * - Record fields
     - ``{state: State, names: string[]}``
   * - Tuple (one Tcl list)
     - ``[Snapshot, string[]]``

Types can be nested and can contain spaces. Keep each type expression on one
comment line. Unknown type names remain visible without a diagnostic.
Incomplete types and unknown annotation tags remain ordinary documentation.
Lua-specific forms such as function types and ``T?`` are not supported.

Analysis
--------

The server collects structured types for parameters, procedure returns,
variable bindings, and variable references. Alias definitions resolve before
procedure body analysis, including aliases declared later in the file.
Recursive and unknown aliases remain unresolved where necessary.

Parameter annotations supply initial type information inside the procedure.
An ``@type`` annotation supplies type information for a ``set`` assignment.
Direct copies, such as ``set copy $value``, carry that type to the new value.
Variable hover shows the type at that use. Later writes clear the type unless
the new value supplies type information. Unknown code and uncertain variable
links also clear affected type information. A branch join keeps a type only
when all paths agree.

A type made entirely of literal values also supplies possible values to the
existing value analysis. For example, ``"enabled"|"disabled"`` can narrow to
``"disabled"`` in the false branch of ``if {$state eq "enabled"}``. These
values can resolve dynamic variable names. A type such as
``string|"enabled"`` does not restrict the value to ``"enabled"``. Known
assignment values take precedence over the annotation's possible values.

An annotated return type follows a single command substitution into its
assigned variable. This uses the resolved procedure, including sourced
procedures, namespace imports, and static command renames. The type keeps the
alias definitions from the procedure's file. Ambiguous or unresolved calls
supply no return type. Concatenated words and substitutions with multiple
commands do not carry a return type.

A tuple result supplies each output type for Tcl's ``lassign`` command. This
also works after copying the tuple to another variable. Extra outputs receive
the empty-string type, as Tcl assigns an empty string after the list ends.

.. code-block:: tcl

   set result [properties::update $actual]
   lassign $result updated changed_names
   # updated has type Snapshot; changed_names has type string[].

The language server and project checker use the same flow inputs. Editing or
removing a provider's annotation refreshes caller types. Checks of arguments,
assignments, and returns are not implemented yet. Effects remain descriptive
text.

Semantic Tokens
---------------

Editors can highlight annotation tags as keywords, names as types or
parameters, record fields as properties, and literals as strings or numbers.
Type punctuation uses operator tokens. Alias names have the declaration
modifier. Descriptions and other comment text keep comment tokens.

Semantic tokens use the collected annotation facts. Write ``@type`` on a
separate comment line:

.. code-block:: tcl

   # @type Snapshot
   set current {}

Tcl does not treat ``#`` after a command argument as a comment marker.
``set current {} # @type Snapshot`` therefore passes extra arguments to
``set``.
