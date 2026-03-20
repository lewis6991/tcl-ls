SHELL := /bin/sh

TCLLIB_REPO ?= https://github.com/tcltk/tcllib.git
TCLLIB_REF ?= tcllib-2-0
CACHE ?= .cache
TCLLIB_DIR ?= $(CACHE)/tcllib-$(subst /,_,$(TCLLIB_REF))
TCL_CHECK_ARGS ?=
DOCS_DIR ?= docs
DOCS_BUILD_DIR ?= $(DOCS_DIR)/_build
SPHINXOPTS ?= -W --keep-going

.PHONY: tcllib
tcllib: $(TCLLIB_DIR)

.PHONY: test
test: $(TCLLIB_DIR)
	TCLLIB_DIR="$(TCLLIB_DIR)" uv run pytest

.PHONY: check
check:
	uv run basedpyright
	uv run ruff check
	uv run ruff format --check
	uv run sphinx-build $(SPHINXOPTS) -b html "$(DOCS_DIR)" "$(DOCS_BUILD_DIR)/html"

.PHONY: docs
docs:
	uv run sphinx-build -b html "$(DOCS_DIR)" "$(DOCS_BUILD_DIR)/html"

.PHONY: check-tcllib
check-tcllib: $(TCLLIB_DIR)
	uv run tcl-check $(TCL_CHECK_ARGS) "$(TCLLIB_DIR)"

.PHONY: generate-builtins
generate-builtins:
	python3 scripts/generate_builtin_commands.py

$(TCLLIB_DIR): | $(CACHE)
	git clone \
		--depth 1 \
		--branch "$(TCLLIB_REF)" \
		"$(TCLLIB_REPO)" \
		"$(TCLLIB_DIR)"

$(CACHE):
	mkdir -p "$@"
