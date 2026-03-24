Getting Started
===============

``tcl-ls`` can be used in three ways:

* as an editor language server
* as a batch checker through ``tcl-check``
* as a metadata helper toolkit through ``tcl-meta``

Prerequisites
-------------

* Python 3.14 or newer
* ``uv`` for local development and repeatable tool execution
* ``tclsh`` if you want to run ``tcl-meta``
* an editor with LSP support if you want interactive language-server features

Install From A Checkout
-----------------------

For repository development, sync the environment once and then prefer
``uv run ...`` for commands:

.. code-block:: sh

   uv sync

If you want plain entry points on your ``PATH``, install the package instead:

.. code-block:: sh

   python -m pip install .

First Commands To Try
---------------------

Check a project tree from the terminal:

.. code-block:: sh

   uv run tcl-check path/to/project

Start the language server on stdio for an editor to manage:

.. code-block:: sh

   uv run tcl-ls

The repository also includes editor-specific setup under ``editors/``:

* a Neovim 0.11+ config under ``editors/nvim``; see :doc:`user-guide/neovim`
* a VS Code extension under ``editors/vscode``; see :doc:`user-guide/vscode`

Print the bundled metadata helper path:

.. code-block:: sh

   uv run tcl-meta helper-path

Local Documentation Build
-------------------------

Build the Sphinx site with:

.. code-block:: sh

   make docs

The generated HTML lives under ``docs/_build/html``.

Where To Go Next
----------------

* Read the :doc:`user-guide/index` for editor, checker, and configuration
  workflows.
* Read :doc:`meta` if you need custom command metadata or Tcl-side helper
  integration.
* Read :doc:`reference/index` for the current CLI and LSP surface area.
