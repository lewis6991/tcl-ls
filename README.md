# tcl-ls

A language server for Tcl

## Maintenance

Refresh builtin subcommand metadata with:

```sh
python3 scripts/generate_builtin_commands.py
```

The generator updates `src/tcl_lsp/data/tcl_builtin_commands.tcl` in place and
supports `--input`, `--output`, `--doc-root`, `--tcl-doc-series`, and
`--version-label` for versioned metadata workflows.
