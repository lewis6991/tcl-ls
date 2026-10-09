Getting Started
===============

Choose the Python package for all three commands, or a prebuilt server for
editor use.

Python Package
--------------

With Python 3.12 or newer, install:

.. code-block:: sh

   python3 -m pip install tcl-ls

The package provides:

* ``tcl-ls`` — the editor language server
* ``tcl-check`` — the batch checker
* ``tcl-meta`` — the metadata generation helper

Prebuilt Server And VS Code Extension
-------------------------------------

Download an asset for your platform from
`GitHub Releases <https://github.com/lewis6991/tcl-ls/releases>`_. Server
archives are built for Linux, macOS, and Windows and do not require a separate
Python installation. Extract the archive, keep its files together, and add
the server directory to your ``PATH``.

The release VS Code extension includes the server. See
:doc:`user-guide/vscode` for installation and settings.

Start Using tcl-ls
------------------

For editor support, follow :doc:`user-guide/neovim`, :doc:`user-guide/vscode`,
or the :doc:`user-guide/language-server` guide for other LSP clients.

To check a file or project directory:

.. code-block:: sh

   tcl-check path/to/project

See :doc:`user-guide/checker` for terminal and CI use. Projects can share
library, metadata, and diagnostic settings in :doc:`user-guide/configuration`.

If commands need custom metadata, start with :doc:`meta`. To work from a
source checkout, see :doc:`development`.
