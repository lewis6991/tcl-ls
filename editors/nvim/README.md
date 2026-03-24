# tcl-ls Neovim config

Neovim 0.11+ LSP config for `tcl-ls`.

## Install the config

Copy the shipped config into your Neovim `lsp/` directory:

```sh
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/nvim/lsp"
cp editors/nvim/lsp/tcl-ls.lua "${XDG_CONFIG_HOME:-$HOME/.config}/nvim/lsp/tcl-ls.lua"
```

Enable it from `init.lua`:

```lua
vim.lsp.enable('tcl-ls')
```

## Default behavior

The shipped config:

* launches `tcl-ls` from `PATH`
* attaches to the `tcl` filetype
* prefers `tcllsrc.tcl`, then `pkgIndex.tcl` for root detection

If your project tree has neither marker, add a `tcllsrc.tcl` file or override
the root detection in your local Neovim config.

## Run from a checkout

Prepare the checkout once:

```sh
uv sync
```

Then override the command in your Neovim config:

```lua
vim.lsp.config('tcl-ls', {
  cmd = { 'uv', 'run', '--directory', '/absolute/path/to/tcl-ls', 'tcl-ls' },
})
vim.lsp.enable('tcl-ls')
```

## Filetype notes

Neovim already maps `.tcl`, `.tm`, `.itcl`, `.itk`, `.tk`, and `.jacl` files
to the `tcl` filetype.
