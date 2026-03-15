SHELL := /bin/sh

TCLLIB_REPO ?= https://github.com/tcltk/tcllib.git
TCLLIB_REF ?= tcllib-2-0
CACHE ?= .cache
TCLLIB_DIR ?= $(CACHE)/tcllib-$(subst /,_,$(TCLLIB_REF))

.PHONY: tcllib
tcllib: $(TCLLIB_DIR)

.PHONY: test
test: $(TCLLIB_DIR)
	TCLLIB_DIR="$(TCLLIB_DIR)" uv run pytest

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
