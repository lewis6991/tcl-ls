# tcl-ls

A language server for Tcl

## Maintenance

Refresh builtin subcommand metadata with:

```sh
python3 scripts/generate_builtin_commands.py
```

The generator updates `meta/tcl8.6/tcl.tcl` in place and
supports `--input`, `--output`, `--doc-root`, `--tcl-doc-series`, and
`--version-label` for versioned metadata workflows.

## Metadata

Metadata files use `meta command` entries:

```tcl
meta command regexp {args} {
    option -start value
    option -- stop
    bind after-options 3..
}
```

The optional body is declarative analysis metadata. Current annotations are:
`option`, `bind`, `ref`, `script-body`, `source`, and `package`.

## Diagnostics

Analyze a Tcl file or project tree with:

```sh
uv run tcl-check path/to/project
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
