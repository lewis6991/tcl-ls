Comment Annotations
===================

Use annotations in Tcl comments to describe procedure parameters and return
values. Both ``# @param`` and ``## @param`` comment forms are
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
       proc update {actual {bound {}}} {
           return [list $actual {}]
       }
   }

Hover, command completion, and signature help show the parameter and return
types. Signature help also shows the active parameter's description. Hover
on an alias declaration shows its definition. Procedure documentation includes
the aliases used by its types, including aliases used by other aliases.

Annotations do not change Tcl execution or argument counts. The server uses
parameter, return, and variable constraints in analysis, as described below.
Expression checks and annotated assignments can report incompatible values.

Annotation Forms
----------------

``# @param name type [description]``
   Describe a parameter by its name in the procedure declaration. The order
   of annotations does not change the order of parameters in the signature.

``# @return type [description]``
   Describe the procedure's single Tcl result. Use a tuple type to describe
   a list with a fixed sequence of elements. Use ``void`` when callers should
   ignore the result.

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
links also clear affected type information. A branch join combines known
alternatives from paths that can continue. A path that returns or raises an
error does not supply values to later statements.

A type made entirely of literal values also supplies possible values to the
existing value analysis. For example, ``"enabled"|"disabled"`` can narrow to
``"disabled"`` in the false branch of ``if {$state eq "enabled"}``. These
values can resolve dynamic variable names. A type such as
``string|"enabled"`` does not restrict the value to ``"enabled"``. Known
assignment values take precedence over the annotation's possible values.

.. _value-constraints:

Value Constraints
-----------------

An annotation describes valid interpretations of a value. It does not add a
runtime class or describe a Tcl object's cached representation. Interpretations
can overlap. For example, ``"42"`` and ``[list 42]`` can both be used in
arithmetic. ``string`` allows any Tcl value; it does not mean nonnumeric.
``integer`` permits Tcl integers, including large integers. ``number`` permits
numeric values. ``integer[]`` describes a Tcl list whose elements satisfy
``integer``.

The checker uses known values before annotations. A contradictory annotation
does not replace the actual value:

.. code-block:: tcl

   # @type integer
   set count auto           ;# invalid-value
   expr {$count + 1}        ;# invalid-expr-operand

Each operator requires an interpretation of its operands:

* ``+ - * / **`` require numbers. Unary ``+`` and ``-`` also require numbers.
* ``% & | ^ << >>`` and unary ``~`` require integers.
* ``! && ||`` and conditions require Tcl expression truth conversion. This
  accepts numeric values as well as boolean words, such as ``yes``.
* ``in`` and ``ni`` require a valid Tcl list on the right.
* ``eq ne`` compare strings. ``== != < <= > >=`` allow Tcl's numeric or string
  comparison. These operators do not reject unrestricted strings.

A definite incompatible operand is an error. A known incompatible alternative
in a union is a warning. An unproved interpretation produces no diagnostic.
For example:

.. code-block:: tcl

   # @param count integer|"auto"
   proc next_count {count} {
       expr {$count + 1}    ;# warning: count can be "auto"
   }

``eq`` and ``ne`` guards can remove literal alternatives. Strict
``string is entier``, ``string is integer``, and ``string is double`` guards
refine the successful branch. Use ``entier`` to accept arbitrary-size integers.
Guards also work with ``!``, ``&&``, ``||``, and ``?:``:

.. code-block:: tcl

   # @param count integer|"auto"
   proc next_count {count} {
       if {$count eq "auto"} {return 0}
       expr {$count + 1}    ;# accepted
   }

Numeric equality retains a value's spelling. Comparing ``$count == 16`` does
not replace a known ``"0x10"`` value with ``"16"``.

Expression text and operand data remain distinct. With
``set formula {1 + 2}``, ``expr $formula`` parses an expression, whereas
``expr {$formula}`` returns the string value. ``expr {$formula + 1}`` reports
an invalid numeric operand. Short-circuit operators skip unused operand
checks, but expression syntax must still be valid in every branch.

When variable reads supply several known expression texts, the checker
examines up to 16 alternatives. A check that fails for every alternative is
an error. A check that fails for only some alternatives is a warning, with
an example of a failing expression. Repeated reads use the same variable
value within each alternative. Possible expression effects are combined
before checking later statements. Unknown text, too many alternatives, and
command results with several possible values remain unproved.

Annotated ``set`` assignments check known literal values against literal,
union, string, numeric, list, and list-element constraints. Unknown aliases
and unsupported structures remain unproved. The checks do not execute project
code. Unknown substitutions clear affected facts. Array expressions and escapes
that the expression parser cannot model remain unproved. Numeric spellings
that differ between Tcl versions also remain unproved, because there is no
configured target version.

Procedure argument and return contracts, math-function contracts, and runtime
domain errors, such as division by zero, are not checked yet.

Return Value Flow
-----------------

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
assignments, and returns are not implemented yet.

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
