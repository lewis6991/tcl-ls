# Project Status

## Current State

This repository contains an early but working bootstrap of a Tcl language server implemented in typed Python.

- Project tooling is set up with `uv`, `pyproject.toml`, `ruff`, `basedpyright`, and `pytest`.
- The codebase is split into three components:
  - `parser`
  - `analysis`
  - `lsp`
- Structured data is modeled with dataclasses and `TypedDict`s.

## Status

### Parser

- [x] Handwritten Tcl parser with typed AST and token models
- [x] Parses:
  - [x] command sequences
  - [x] comments
  - [x] newline and `;` separators
  - [x] bare words
  - [x] braced words
  - [x] quoted words
  - [x] variable substitution
  - [x] nested command substitution
- [x] Tracks source spans/positions for tokens and AST nodes
- [x] Supports embedded-script parsing with preserved absolute positions
- [x] Emits syntax diagnostics for:
  - [x] unmatched quotes
  - [x] unmatched braces
  - [x] unmatched command-substitution brackets
  - [x] malformed variable substitutions
- [ ] Full Tcl 8.6 language coverage is not implemented
- [ ] No parser support is documented or tested for many advanced Tcl constructs, including:
  - [ ] argument expansion syntax like `{*}$args`
  - [ ] array variable syntax like `$name(index)`
  - [ ] richer escape handling beyond the current simple escape support
  - [ ] package- or extension-specific syntax
  - [ ] TclOO and other higher-level ecosystems
- [ ] The parser is intentionally conservative and currently targeted at the core syntax needed for the MVP server

### Analysis

- [x] Separate fact extraction and resolution pipeline
- [x] Extracts and indexes:
  - [x] `proc` declarations
  - [x] procedure parameters
  - [x] top-level `namespace eval ... { ... }`
  - [x] `package require` / `package provide`
  - [x] conservative `package ifneeded` entries from `pkgIndex.tcl`
  - [x] `set` bindings/references
  - [x] `append` / `incr` / `lappend` variable writers
  - [x] `gets`, `lassign`, and `scan` output variable bindings
  - [x] `global` / `variable` namespace-variable links
  - [x] conservative `upvar` alias bindings
  - [x] `vwait` global variable references
  - [x] `foreach` / `lmap` loop variable bindings
  - [x] `for` / `while` body analysis
  - [x] variable substitutions
  - [x] statically named command calls
  - [x] static `namespace import` command imports
- [x] Workspace procedure and package metadata indexes for cross-file navigation and package lookup
- [x] Resolution states are explicit:
  - [x] `resolved`
  - [x] `unresolved`
  - [x] `ambiguous`
  - [x] `dynamic`
- [x] Semantic diagnostics currently implemented:
  - [x] ambiguous variable bindings in procedure scope
  - [x] duplicate procedure declarations
  - [x] missing option values for commands with metadata option specs
  - [x] unknown options for commands with metadata option specs
  - [x] wrong argument counts for statically resolved commands with simple arity metadata
  - [x] unresolved commands
  - [x] unresolved packages
  - [x] unresolved variables in procedure scope
- [x] Hover/definition/reference data generation
- [x] Document symbols for namespaces and procedures
- [x] Conservative local package inference from nearby `pkgIndex.tcl`
- [x] Lazy loading of package provider files discovered through local `pkgIndex.tcl`
- [x] Bundled Tcl builtin metadata for default command recognition and hover docs
- [ ] No full control-flow analysis
- [ ] No runtime evaluation of dynamic Tcl features
- [ ] Embedded/body analysis is still selective; it covers `proc`, top-level `namespace eval`, `if`, `catch`, `switch`, `foreach`, `lmap`, `for`, and `while`, but many Tcl constructs are still not analyzed
- [ ] No modeling of:
  - [ ] `eval`
  - [ ] `uplevel`
  - [ ] dynamically constructed command names
  - [ ] `source`-based project loading
  - [ ] full package resolution for external/interpreter-installed packages
  - [ ] TclOO/class systems
- [ ] Global and namespace variable resolution is still conservative outside explicit links (`global` / `variable` / `upvar`) and statically qualified names
- [ ] Workspace indexing is still narrow; beyond procedures and package metadata there is no rich global symbol database
- [ ] Builtin coverage is limited to default Tcl commands; Tcl/Tk and extension-specific commands may still be reported as unresolved
- [ ] Diagnostics are intentionally limited to high-confidence cases

### LSP and Editor Integration

- [x] Minimal stdio JSON-RPC/LSP server
- [x] Supported methods:
  - [x] `initialize`
  - [x] `initialized`
  - [x] `shutdown`
  - [x] `exit`
  - [x] `textDocument/didOpen`
  - [x] `textDocument/didChange`
  - [x] `textDocument/didClose`
  - [x] `textDocument/definition`
  - [x] `textDocument/references`
  - [x] `textDocument/hover`
  - [x] `textDocument/documentSymbol`
- [x] Diagnostics are published on open/change/close
- [x] Full-document sync model
- [x] In-memory document store and reanalysis of currently managed/open documents on updates
- [x] Local package-root discovery and `pkgIndex.tcl` scanning for opened documents
- [ ] completion
- [ ] signature help
- [ ] rename
- [ ] code actions
- [ ] formatting
- [ ] semantic tokens
- [ ] document highlights
- [ ] workspace symbols
- [ ] code lens
- [ ] inlay hints
- [ ] LSP position handling does not yet account for UTF-16 code-unit semantics or negotiate a `positionEncoding`
- [ ] No incremental parsing or incremental semantic analysis
- [ ] No incremental text sync support
- [ ] No file watching or full automatic workspace discovery; unopened files are only indexed opportunistically through local package inference
- [ ] No persistent cache/database on disk
- [ ] No Neovim/VS Code plugin packaging in this repository
- [ ] No CI configuration has been added yet

### Tests

- [x] Parser tests cover:
  - [x] nested substitutions
  - [x] syntax error diagnostics
  - [x] embedded-script span handling
- [x] Analysis tests cover:
  - [x] procedure/parameter resolution
  - [x] duplicate and unresolved diagnostics
  - [x] namespace-qualified procedure resolution
- [x] LSP tests cover:
  - [x] cross-document definition/reference/hover behavior
  - [x] diagnostics publication
  - [x] local package inference from `pkgIndex.tcl`
  - [x] unresolved package diagnostics
  - [x] stdio request/response round trip

## Practical Summary

Right now the project is a solid typed bootstrap for a Tcl LSP:

- syntax parsing works for the tested core forms
- semantic analysis works for a small, statically analyzable Tcl subset plus conservative local package inference via `pkgIndex.tcl`
- navigation features work for that subset
- the server can speak enough LSP to be used experimentally in an editor

It is not yet a full Tcl language server, and the biggest missing areas are broader Tcl semantics, dynamic-language handling beyond conservative fallbacks, and additional editor features beyond the MVP navigation surface.
