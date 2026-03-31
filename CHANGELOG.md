# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

## 0.1.0 - 2026-03-31

Initial public alpha release.

### Added

- A typed Tcl parser with source spans, syntax diagnostics, and embedded-script
  parsing for core Tcl forms.
- A conservative static analysis pipeline with diagnostics, hover, definition,
  declaration, implementation, references, rename, completion, signature help,
  semantic tokens, document links, and workspace symbols.
- Command-line entry points for ``tcl-ls``, ``tcl-check``, and ``tcl-meta``.
- Bundled Tcl and Tcllib metadata, packaged frozen-server builds, and editor
  integration assets for VS Code and Neovim.

### Notes

- This release is intentionally alpha-quality. It is already useful for early
  adopters, but Tcl analysis remains conservative and many dynamic language
  features are still outside the current scope.
