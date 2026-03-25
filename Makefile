SHELL := /bin/sh

ROOT_DIR := $(CURDIR)
PYTHON ?= python3

# Tcllib checkout and tests.
TCLLIB_REPO ?= https://github.com/tcltk/tcllib.git
TCLLIB_REF ?= tcllib-2-0
CACHE ?= .cache
TCLLIB_DIR ?= $(CACHE)/tcllib-$(subst /,_,$(TCLLIB_REF))

.PHONY: tcllib
tcllib: $(TCLLIB_DIR)

.PHONY: test
test: $(TCLLIB_DIR)
	TCLLIB_DIR="$(TCLLIB_DIR)" uv run pytest

$(TCLLIB_DIR): | $(CACHE)
	git clone \
		--depth 1 \
		--branch "$(TCLLIB_REF)" \
		"$(TCLLIB_REPO)" \
		"$(TCLLIB_DIR)"

$(CACHE):
	mkdir -p "$@"

# Docs and checks.
DOCS_DIR ?= docs
DOCS_BUILD_DIR ?= $(DOCS_DIR)/_build
SPHINXOPTS ?= -W --keep-going

.PHONY: check
check:
	uv run basedpyright
	uv run ruff check
	uv run ruff format --check
	uv run sphinx-build $(SPHINXOPTS) -b html "$(DOCS_DIR)" "$(DOCS_BUILD_DIR)/html"

.PHONY: docs
docs:
	uv run sphinx-build -b html "$(DOCS_DIR)" "$(DOCS_BUILD_DIR)/html"

# Tcl checker.
TCL_CHECK_ARGS ?=

.PHONY: check-tcllib
check-tcllib: $(TCLLIB_DIR)
	uv run tcl-check $(TCL_CHECK_ARGS) "$(TCLLIB_DIR)"

# Builtin metadata generation.
.PHONY: generate-builtins
generate-builtins:
	$(PYTHON) scripts/generate_builtin_commands.py

# Release version stamping.
RELEASE_CHANNEL ?= stable
RELEASE_RUN_NUMBER ?= 1
RELEASE_VERSION ?= $(shell \
	$(PYTHON) scripts/release_version.py compute \
		--channel "$(RELEASE_CHANNEL)" \
		--run-number "$(RELEASE_RUN_NUMBER)")

.PHONY: release-stamp
release-stamp:
	$(PYTHON) scripts/release_version.py stamp "$(RELEASE_VERSION)"

# PyInstaller packaging.
BUILD_DIR ?= build
DIST_DIR ?= dist
PYINSTALLER_CONFIG_DIR ?= $(BUILD_DIR)/pyinstaller-config
PYINSTALLER_DIST_DIR ?= $(BUILD_DIR)/release
PYINSTALLER_WORK_DIR ?= $(BUILD_DIR)/pyinstaller
PYINSTALLER_SPEC ?= tcl-ls.spec
TCL_LS_FROZEN_DIR ?= $(PYINSTALLER_DIST_DIR)/tcl-ls
PYINSTALLER_EXECUTABLE ?= $(shell $(PYTHON) scripts/platform_target.py executable-name)
RELEASE_PLATFORM ?= $(shell $(PYTHON) scripts/platform_target.py release-platform)
ARCHIVE_EXTENSION ?= $(shell $(PYTHON) scripts/platform_target.py archive-extension)

.PHONY: pyinstaller-tcl-ls
pyinstaller-tcl-ls:
	PYINSTALLER_CONFIG_DIR="$(ROOT_DIR)/$(PYINSTALLER_CONFIG_DIR)" \
	uv run pyinstaller \
		--noconfirm \
		--clean \
		--distpath "$(PYINSTALLER_DIST_DIR)" \
		--workpath "$(PYINSTALLER_WORK_DIR)" \
		"$(PYINSTALLER_SPEC)"

.PHONY: pyinstaller-tcl-ls-smoke
pyinstaller-tcl-ls-smoke: pyinstaller-tcl-ls
	uv run python scripts/smoke_pyinstaller_lsp.py \
		"$(TCL_LS_FROZEN_DIR)/$(PYINSTALLER_EXECUTABLE)"

.PHONY: pyinstaller-tcl-ls-archive
pyinstaller-tcl-ls-archive: pyinstaller-tcl-ls
	$(PYTHON) scripts/package_release_asset.py \
		--source "$(TCL_LS_FROZEN_DIR)" \
		--output "$(DIST_DIR)/tcl-ls-$(RELEASE_VERSION)-$(RELEASE_PLATFORM).$(ARCHIVE_EXTENSION)" \
		--root-name "tcl-ls-$(RELEASE_VERSION)-$(RELEASE_PLATFORM)" \
		--include LICENSE \
		--include README.md
