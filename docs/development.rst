Development
===========

This page is for contributors and maintainers working on the ``tcl-ls``
codebase itself.

Repository Layout
-----------------

The repository is organized into a few core areas:

* ``src/tcl_lsp/parser`` for the handwritten Tcl parser and AST model
* ``src/tcl_lsp/analysis`` for fact extraction, resolution, diagnostics, and
  metadata effects
* ``src/tcl_lsp/lsp`` for the pygls-based language server surface
* ``meta/`` for bundled Tcl and Tcllib metadata
* ``tests/`` for parser, analysis, checker, and LSP coverage
* ``docs/`` for the Sphinx documentation site

Common Local Commands
---------------------

Set up and run the usual development workflow with:

.. code-block:: sh

   uv sync
   make test
   make check
   make docs

Useful one-off commands:

.. code-block:: sh

   uv run pytest tests/lsp/test_lsp.py
   uv run tcl-check path/to/project
   uv build
   make check-tcllib
   make generate-builtins
   make pyinstaller-tcl-ls-smoke

``make test`` clones ``tcllib`` into ``.cache/`` on first use so integration
tests can run against a realistic package tree.

Packaging And Release Validation
--------------------------------

The Python package and frozen server builds are part of the normal maintenance
surface:

* ``uv build`` writes the source distribution and wheel under ``dist/``
* ``uvx twine check dist/*.whl dist/*.tar.gz`` validates the built package
  metadata before upload
* ``make pyinstaller-tcl-ls-smoke`` builds the frozen server and validates a
  real LSP initialize/shutdown/exit handshake
* GitHub release workflows build packaged server archives and bundled VS Code
  extensions for Linux, macOS, and Windows

Before a release, verify that the package metadata in ``pyproject.toml``,
install instructions in ``README.md`` / ``docs/``, and release notes in
``CHANGELOG.md`` are all current.

Current Scope
-------------

The project is already a working typed bootstrap, but it is intentionally
conservative:

* the parser covers the tested core Tcl forms rather than the full language
* semantic analysis focuses on statically knowable behavior
* builtin metadata is strong for core Tcl, but extension ecosystems still need
  expansion
* editor support is centered on diagnostics, navigation, completion, and
  semantic tokens

Areas that still need more work include richer Tcl semantics, broader metadata
coverage, automatic workspace discovery, and additional editor features such as
formatting and code actions.

Documentation Maintenance
-------------------------

Documentation is part of the normal quality bar:

* ``make docs`` builds the HTML site
* ``make check`` treats Sphinx warnings as errors
* user-facing behavior changes should update the relevant page under ``docs/``

The more detailed engineering backlog and implementation notes still live in
``STATUS.md``.
