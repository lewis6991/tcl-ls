Project Configuration
=====================

Both ``tcl-ls`` and ``tcl-check`` automatically read project-local config from
``tcllsrc.tcl`` files.

Discovery Rules
---------------

When the server opens a document, or when the checker analyzes a path, the
tool walks upward from that path toward the filesystem root and collects every
``tcllsrc.tcl`` file it finds. Relative paths inside each config file are
resolved relative to the directory that contains that file.

Supported Commands
------------------

``tcllsrc.tcl`` currently supports these static commands:

* ``plugin-path path``
* ``lib-path path``
* ``library-path path``

Paths must be literal strings. Dynamic Tcl in the config file is rejected.

Typical Example
---------------

.. code-block:: tcl

   plugin-path .tcl-ls
   lib-path ../vendor/tcllib

``plugin-path`` accepts:

* a directory containing ``*.meta.tcl`` files
* a single ``.meta.tcl`` file
* a Tcl plugin script ending in ``.tcl`` or ``.tm``

When a plugin script is passed, sibling metadata files are discovered from the
script's parent directory.

``lib-path`` and ``library-path`` are synonyms. Their directories are scanned
for ``pkgIndex.tcl`` files so external library trees can satisfy
``package require`` without being copied into the main project.

When To Use Config Vs CLI Flags
-------------------------------

Use ``tcllsrc.tcl`` for project settings that should apply to every editor and
checker run. Use the ``tcl-check --plugin-path`` flag for temporary or
one-off metadata injection.

