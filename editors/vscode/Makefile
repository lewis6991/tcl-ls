SHELL := /bin/sh

ROOT_DIR := $(abspath ../..)
PYTHON ?= python3
NPM ?= npm

# npm lifecycle.
.PHONY: install
install:
	$(NPM) ci

.PHONY: check
check:
	$(NPM) run check

# Bundled server staging.
BUILD_DIR ?= $(ROOT_DIR)/build
TCL_LS_FROZEN_DIR ?= $(BUILD_DIR)/release/tcl-ls

.PHONY: stage-server
stage-server:
	$(PYTHON) scripts/stage_vscode_server.py \
		--source "$(TCL_LS_FROZEN_DIR)" \
		--destination server

# VSIX packaging.
DIST_DIR ?= $(ROOT_DIR)/dist
VSCODE_TARGET ?= $(shell $(PYTHON) $(ROOT_DIR)/scripts/platform_target.py vscode-target)
VSCODE_PACKAGE_FLAGS ?=
VSCODE_VERSION ?= $(shell \
	$(PYTHON) -c 'import json; from pathlib import Path; print(json.loads(Path("package.json").read_text())["version"])')
VSCODE_VSIX_NAME ?= tcl-ls-vscode-$(VSCODE_VERSION)$(if $(VSCODE_TARGET),@$(VSCODE_TARGET),).vsix

.PHONY: clean-staged-server
clean-staged-server:
	rm -rf server

.PHONY: package-vsix
package-vsix: install check
	mkdir -p "$(DIST_DIR)"
	$(NPM) exec --package @vscode/vsce -- vsce package \
		$(if $(VSCODE_TARGET),--target "$(VSCODE_TARGET)",) \
		$(VSCODE_PACKAGE_FLAGS) \
		-o "$(DIST_DIR)/$(VSCODE_VSIX_NAME)"

.PHONY: vsix
vsix: clean-staged-server
	$(MAKE) package-vsix

.PHONY: bundled-vsix
bundled-vsix:
	$(MAKE) -C "$(ROOT_DIR)" pyinstaller-tcl-ls
	$(MAKE) stage-server
	$(MAKE) package-vsix

.PHONY: release-assets-local
release-assets-local:
	$(MAKE) -C "$(ROOT_DIR)" pyinstaller-tcl-ls-archive
	$(MAKE) bundled-vsix
