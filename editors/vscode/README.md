# tcl-ls-vscode

VS Code extension for the `tcl-ls` language server.

## What it does

The extension:

* associates `.tcl`, `.tm`, and `.test` files with a `tcl` language id
* starts `tcl-ls` over stdio
* exposes a `tcl-ls: Restart Language Server` command
* restarts the server when `tcllsrc.tcl`, `pkgIndex.tcl`, or `*.meta.tcl`
  files change

## Build and install a VSIX

Marketplace and release builds bundle a frozen `tcl-ls` server inside the
extension. For a local build that behaves the same way on your current
platform, use the VS Code makefile:

```sh
uv sync
make -C editors/vscode bundled-vsix
```

This writes a file like `dist/tcl-ls-vscode-<version>@<target>.vsix`. Install
it with:

```sh
code --install-extension /absolute/path/to/dist/tcl-ls-vscode-<version>@<target>.vsix --force
```

If you only want the extension package and plan to point it at a checkout or
PATH server yourself, use:

```sh
make -C editors/vscode vsix
```

You can also use `Extensions: Install from VSIX...` in the VS Code UI.

## Configure the server

Prefer explicit settings. That is more reliable than PATH-dependent launch
behavior, especially on macOS when VS Code is launched as a GUI app.

Recommended for local development from a checkout:

```json
{
  "tcl-ls.server.repoRoot": "/absolute/path/to/tcl-ls"
}
```

With that setting in place, the extension launches:

```sh
/absolute/path/to/tcl-ls/.venv/bin/tcl-ls
```

The checkout should already have been prepared with:

```sh
uv sync
```

If you want to bypass `repoRoot`, you can configure the command directly:

```json
{
  "tcl-ls.server.command": "/absolute/path/to/tcl-ls/.venv/bin/tcl-ls",
  "tcl-ls.server.args": []
}
```

If `tcl-ls.server.args` is empty, `tcl-ls.server.command` can also be a full
command line:

```json
{
  "tcl-ls.server.command": "/opt/homebrew/bin/uv run --directory=/absolute/path/to/tcl-ls tcl-ls",
  "tcl-ls.server.args": []
}
```

Quote any path that contains spaces.

Leave `tcl-ls.server.repoRoot` and `tcl-ls.server.cwd` empty to disable them.
`tcl-ls.server.cwd` accepts `${workspaceFolder}` and
`${workspaceFolderBasename}` placeholders.

## Fallback behavior

If neither `tcl-ls.server.command` nor `tcl-ls.server.repoRoot` is set, the
extension prefers a bundled server from the packaged extension. If there is no
bundled server, it falls back to `tcl-ls` on `PATH`.

## Development host

The `F5` Extension Development Host flow still works, but the intended local
workflow is building and installing a VSIX.
