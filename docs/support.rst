Support
=======

``tcl-ls`` is still an early project, so good bug reports and clear local
reproduction details matter more than polished integrations.

Before Opening An Issue
-----------------------

Collect the smallest reproduction you can:

* the Tcl source snippet that shows the problem
* the exact command or editor setup you used
* any relevant ``tcllsrc.tcl`` contents
* whether the failure is in ``tcl-ls``, ``tcl-check``, or ``tcl-meta``
* what you expected to happen instead

Useful local checks:

.. code-block:: sh

   uv run tcl-check --context-lines 2 path/to/project
   uv run tcl-meta helper-path
   make check

Common Troubleshooting Paths
----------------------------

If builtin or project commands show up as unresolved:

* confirm the file is inside the right project root
* add project metadata with ``plugin-path`` or ``--plugin-path``
* make sure custom metadata uses the ``.meta.tcl`` suffix

If ``package require`` cannot be resolved:

* confirm the relevant library tree contains ``pkgIndex.tcl``
* add that tree with ``lib-path`` or ``library-path``
* remember that package discovery is conservative, not runtime-evaluated

If editor features are missing entirely:

* make sure the client launches ``tcl-ls`` over stdio
* make sure the file is opened with a Tcl filetype
* remember that no editor plugin package ships with this repository yet

Setting Expectations
--------------------

Some gaps are expected today rather than immediate bugs:

* dynamic Tcl patterns such as ``eval`` and ``uplevel`` are not modeled fully
* analysis intentionally prefers false negatives over noisy false positives
* many higher-level Tcl ecosystems still need more bundled metadata coverage

