# tcl-ls-vscode

The extension provides Tcl language support for VS Code 1.90 or newer. It
recognizes `.tcl`, `.tm`, and `.test` files and starts the server over stdio.

## Install

Download the `.vsix` for your platform from
[GitHub Releases](https://github.com/lewis6991/tcl-ls/releases). Release
extensions include the server, so no separate Python installation is needed.

Use **Extensions: Install from VSIX...** in VS Code, or run:

```sh
code --install-extension /path/to/tcl-ls-vscode-<version>@<target>.vsix
```

## Server settings

The extension selects a server in this order:

1. `tcl-ls.server.command`, if set
2. the virtual environment under `tcl-ls.server.repoRoot`, if set
3. the server bundled with the extension
4. `tcl-ls` on `PATH`

| Setting | Purpose |
| --- | --- |
| `tcl-ls.server.command` | Executable path or name. Empty by default. |
| `tcl-ls.server.args` | Arguments for an explicit command. Defaults to `[]`. |
| `tcl-ls.server.repoRoot` | tcl-ls checkout to use when no command is set. Empty by default. |
| `tcl-ls.server.cwd` | Server working directory. Relative paths start at the first workspace folder. Empty uses the launcher's default. |
| `tcl-ls.server.restartOnProjectFileChanges` | Restart when `tcllsrc.tcl`, `pkgIndex.tcl`, or `*.meta.tcl` is created, changed, or deleted. Defaults to `true`. |

For an explicitly installed server:

```json
{
  "tcl-ls.server.command": "/absolute/path/to/tcl-ls",
  "tcl-ls.server.args": []
}
```

If `server.args` is empty, `server.command` can contain a full command line;
quote paths containing spaces. The `repoRoot` and `cwd` settings accept
`${workspaceFolder}` and `${workspaceFolderBasename}` placeholders. Clear a
path setting with an empty string.

Use **tcl-ls: Restart Language Server** to restart manually. Startup errors
and restart details appear in the **tcl-ls** output channel.

## Use a checkout

Run `uv sync` in the tcl-ls repository, then set:

```json
{
  "tcl-ls.server.repoRoot": "/absolute/path/to/tcl-ls"
}
```

Clear `tcl-ls.server.command` so this setting takes effect.

## Build the extension

From a prepared repository checkout, with Node.js and npm available:

```sh
make -C editors/vscode bundled-vsix
```

This builds the server and writes
`dist/tcl-ls-vscode-<version>@<target>.vsix`. Install it as described above.
Use `make -C editors/vscode vsix` to package the extension without a server
and select one through the settings. The `F5` Extension Development Host is
also available for debugging.
