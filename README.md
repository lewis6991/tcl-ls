# tcl-ls

A Tcl language server, batch checker, and metadata toolkit. It provides
diagnostics, navigation, completion, rename, signature help, and semantic tokens.
The project is in alpha and analyzes Tcl statically; dynamic APIs can need
additional metadata.

## Install

The Python package requires Python 3.12 or newer:

```sh
python3 -m pip install tcl-ls
```

Standalone server archives and VS Code extension packages are also available
from [GitHub Releases](https://github.com/lewis6991/tcl-ls/releases).
See [Getting Started](https://lewis6991.github.io/tcl-ls/getting-started.html)
for installation choices.

## Use

Set up the server in [Neovim](editors/nvim/README.md) or
[VS Code](editors/vscode/README.md), or connect another editor's LSP client to
`tcl-ls` over stdio.

Check a Tcl file or project directory from the terminal:

```sh
tcl-check path/to/project
```

Use `tcllsrc.tcl` to load project metadata, locate libraries, and configure
diagnostics. The [documentation](https://lewis6991.github.io/tcl-ls/) covers:

* [Project configuration](https://lewis6991.github.io/tcl-ls/user-guide/configuration.html)
* [Metadata authoring and generation](https://lewis6991.github.io/tcl-ls/meta.html)
* [Command-line options](https://lewis6991.github.io/tcl-ls/reference/cli.html)
* [Troubleshooting](https://lewis6991.github.io/tcl-ls/support.html)
* [Development and documentation builds](https://lewis6991.github.io/tcl-ls/development.html)
