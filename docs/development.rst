Development
===========

Run commands from the repository root. The Python tools use ``uv``.

Setup And Checks
----------------

.. code-block:: sh

   uv sync
   make test
   make check

``make test`` fetches Tcllib into ``.cache/`` on first use and runs the test
suite. ``make check`` runs type, lint, formatting, and documentation checks,
with Sphinx warnings treated as errors.

For focused tests or a local checker run:

.. code-block:: sh

   uv run pytest tests/lsp
   uv run tcl-check path/to/project

To inspect diagnostics across the cached Tcllib tree:

.. code-block:: sh

   make check-tcllib TCL_CHECK_ARGS="--context-lines=1 --fail-on-diagnostics"

Repository Layout
-----------------

* ``src/tcl_lsp/parser``: Tcl parser and syntax tree
* ``src/tcl_lsp/analysis``: fact extraction, resolution, diagnostics, and metadata effects
* ``src/tcl_lsp/lsp``: language server
* ``src/tcl_lsp/checker``: batch analysis and terminal reporting
* ``meta/``: bundled Tcl and Tcllib metadata
* ``editors/``: Neovim config and VS Code extension
* ``tests/``: parser, analysis, checker, and LSP tests
* ``docs/``: Sphinx site

Metadata Maintenance
--------------------

Refresh generated builtin subcommand metadata with:

.. code-block:: sh

   make generate-builtins

This updates ``meta/tcl8.6/tcl.meta.tcl``. The generator,
``scripts/generate_builtin_commands.py``, accepts ``--input``, ``--output``,
``--doc-root``, ``--tcl-doc-series``, and ``--version-label`` for other inputs
or Tcl versions. See :doc:`meta` for authoring metadata and generating tool
inventories.

Documentation
-------------

Update the relevant guide or reference when behavior changes. Build the HTML
site with:

.. code-block:: sh

   make docs

Open ``docs/_build/html/index.html``. The Neovim and VS Code pages include
``editors/nvim/README.md`` and ``editors/vscode/README.md``; edit those source
files to keep the repository and published guides consistent.

Packaging
---------

.. code-block:: sh

   uv build
   uvx twine check dist/*.whl dist/*.tar.gz
   make pyinstaller-tcl-ls-smoke

The first two commands build and validate the Python distributions in ``dist/``.
The smoke target builds a standalone server and checks an LSP
initialize/shutdown/exit exchange. ``make pyinstaller-tcl-ls-archive`` also
packages the server for distribution. See :doc:`user-guide/vscode` for VSIX
builds.

Before a release, check the version in ``pyproject.toml``, installation
instructions, and ``CHANGELOG.md``. Engineering plans and implementation notes
are kept in ``STATUS.md``.
