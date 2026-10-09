# tcl-ls Neovim config

The supplied LSP config requires Neovim 0.11 or newer and a `tcl-ls`
executable on the editor's `PATH`. See
[Getting Started](https://lewis6991.github.io/tcl-ls/getting-started.html)
for server installation.

## Install the config

From this repository, copy the config into your Neovim `lsp/` directory:

```sh
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/nvim/lsp"
cp editors/nvim/lsp/tcl-ls.lua "${XDG_CONFIG_HOME:-$HOME/.config}/nvim/lsp/tcl-ls.lua"
```

Enable it in `init.lua`:

```lua
vim.lsp.enable('tcl-ls')
```

The config attaches to the `tcl` filetype and prefers `tcllsrc.tcl`, then
`pkgIndex.tcl`, for root detection. If neither marker exists, add a
`tcllsrc.tcl` file or override root detection in your Neovim config.

## Use a checkout

After running `uv sync` in the tcl-ls checkout, set its absolute path before
enabling the config:

```lua
vim.lsp.config('tcl-ls', {
  cmd = { 'uv', 'run', '--directory', '/absolute/path/to/tcl-ls', 'tcl-ls' },
})
vim.lsp.enable('tcl-ls')
```
