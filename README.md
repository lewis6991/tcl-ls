# tcl-ls

A Tcl language server, checker, and metadata toolkit implemented in typed
Python.

## Install

`tcl-ls` currently targets Python 3.14 or newer.

Install from PyPI with:

```sh
python3 -m pip install tcl-ls
```

You can also download packaged server archives and editor assets from the
[GitHub Releases](https://github.com/lewis6991/tcl-ls/releases) page.

This installs three command-line entry points:

* `tcl-ls` for the stdio language server
* `tcl-check` for batch diagnostics
* `tcl-meta` for Tcl metadata-helper workflows

For local development from a checkout, sync the environment once and prefer
`uv run ...` for commands you do not want to install globally:

```sh
uv sync
```

## Current Scope

This is an alpha release aimed at early adopters. The server is already useful
for diagnostics, navigation, completion, rename, signature help, semantic
tokens, and metadata-assisted checking, but it still analyzes Tcl
conservatively and does not try to model the full dynamic runtime.

## Documentation

Published docs are available at
<https://lewis6991.github.io/tcl-ls/>.

Build the Sphinx docs locally with:

```sh
make docs
```

The rendered site is written to `docs/_build/html/index.html` and covers
getting started, editor and checker workflows, metadata authoring, support,
and development notes.

Editor-specific helpers shipped in this repository:

* `editors/vscode` for the VS Code extension
* `editors/nvim` for the Neovim 0.11+ built-in LSP config

## Maintenance

Refresh builtin subcommand metadata with:

```sh
python3 scripts/generate_builtin_commands.py
```

The generator updates `meta/tcl8.6/tcl.meta.tcl` in place and
supports `--input`, `--output`, `--doc-root`, `--tcl-doc-series`, and
`--version-label` for versioned metadata workflows.

## Metadata

Metadata files use the `*.meta.tcl` suffix and `meta command` entries:

```tcl
meta command regexp {args} {
    option -start value
    option -- stop
    bind after-options 3..
}
```

The optional body is declarative analysis metadata. Current annotations are:
`option`, `keyword`, `subcommand`, `bind`, `ref`, `script-body`,
`source`, and `package`.

## Diagnostics

Install the package first so the CLI entry points are available:

```sh
python3 -m pip install tcl-ls
```

Analyze a Tcl file or project tree with:

```sh
tcl-check path/to/project
```

In an interactive terminal, the checker prepares package-scoped workspaces
(directories rooted by `pkgIndex.tcl`), then prints final grouped diagnostics
with source context and a finished summary as each workspace is analyzed. Use
`--color=always|never|auto` and `--context-lines=N` to tune the terminal
output.

To inspect the current diagnostics emitted for `tcllib`, use:

```sh
make check-tcllib
```

Pass extra checker flags through `make` with:

```sh
make check-tcllib TCL_CHECK_ARGS="--context-lines=1 --fail-on-diagnostics"
```

Project-local config can live in `tcllsrc.tcl`. Supported commands are:

```tcl
plugin-path .tcl-ls/sample.tcl
lib-path ../tcllib
```

Configured paths are resolved relative to the config file. `lib-path` roots are
scanned for `pkgIndex.tcl` files so external library trees can satisfy
`package require` without moving them into the project.

To build metadata inside a tool-specific Tcl shell, source the bundled helper
reported by:

```sh
tcl-meta helper-path
```

Then, inside that tool Tcl shell, write metadata directly with:

```tcl
tcl-meta build-file output.meta.tcl
```

For local development in this repository, use `uv run ...` when you want to
run the CLI without installing it first.
