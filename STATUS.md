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
  - [x] `set` bindings/references
  - [x] basic `foreach` loop variable bindings
  - [x] variable substitutions
  - [x] statically named command calls
- [x] Workspace procedure index for cross-file navigation across currently managed/open documents
- [x] Resolution states are explicit:
  - [x] `resolved`
  - [x] `unresolved`
  - [x] `ambiguous`
  - [x] `dynamic`
- [x] Semantic diagnostics currently implemented:
  - [x] duplicate procedure declarations
  - [x] unresolved commands
  - [x] unresolved variables in procedure scope
- [x] Hover/definition/reference data generation
- [x] Document symbols for namespaces and procedures
- [ ] No full control-flow analysis
- [ ] No runtime evaluation of dynamic Tcl features
- [ ] Embedded/body analysis is currently limited to `proc`, top-level `namespace eval`, and basic `foreach`; bodies for most other Tcl control structures are not analyzed
- [ ] No modeling of:
  - [ ] `eval`
  - [ ] `global`
  - [ ] `uplevel`
  - [ ] `upvar`
  - [ ] `variable`
  - [ ] dynamically constructed command names
  - [ ] `source`-based project loading
  - [ ] package resolution
  - [ ] TclOO/class systems
- [ ] Global variable resolution is intentionally conservative
- [ ] Workspace indexing is currently centered on procedures; there is no rich global symbol database beyond the current procedure index
- [ ] Builtin command recognition is currently limited to a small hardcoded subset, so some valid Tcl builtins may still be reported as unresolved
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
- [ ] No file watching, automatic workspace discovery, or indexing of unopened workspace files
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
  - [x] stdio request/response round trip

## Practical Summary

Right now the project is a solid typed bootstrap for a Tcl LSP:

- syntax parsing works for the tested core forms
- semantic analysis works for a small, statically analyzable Tcl subset
- navigation features work for that subset
- the server can speak enough LSP to be used experimentally in an editor

It is not yet a full Tcl language server, and the biggest missing areas are broader Tcl semantics, dynamic-language handling beyond conservative fallbacks, and additional editor features beyond the MVP navigation surface.
