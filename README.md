# tcl-ls

A language server for Tcl

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
python3 -m pip install .
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
