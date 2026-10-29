PROJECT=sphinx_linkcheck_diff
UV_TEST_GROUPS := "--group=dev"
UV_LINT_GROUPS := "--group=lint" "--group=types"

include common.mk

.PHONY: format
format: format-ruff format-codespell format-prettier  ## Run all automatic formatters

.PHONY: lint
lint: lint-code  ## Run all linters

# This repo's documentation is its markdown files, which prettier lints
# (see lint-prettier in common.mk). The setup-docs and docs-lint targets
# exist because starflow's lint workflow calls them; they have nothing
# to set up beyond the lint environment.
.PHONY: setup-docs
setup-docs: setup-lint  ## Set up the documentation environment

.PHONY: docs-lint
docs-lint: lint-prettier  ## Lint the documentation

.PHONY: lint-code
lint-code: lint-ruff lint-codespell lint-mypy lint-prettier lint-pyright lint-shellcheck lint-twine  ## Run the code linters

.PHONY: pack
pack: pack-pip  ## Build all packages

.PHONY: publish
publish: publish-pypi  ## Publish packages

.PHONY: publish-pypi
publish-pypi: clean pack-pip lint-twine  ## Publish Python packages to pypi
	uv tool run twine upload dist/*

# Find dependencies that need installing
APT_PACKAGES :=
ifeq ($(wildcard /usr/include/libxml2/libxml/xpath.h),)
APT_PACKAGES += libxml2-dev
endif
ifeq ($(wildcard /usr/include/libxslt/xslt.h),)
APT_PACKAGES += libxslt1-dev
endif
ifeq ($(wildcard /usr/share/doc/python3-venv/copyright),)
APT_PACKAGES += python3-venv
endif

# Used for installing build dependencies in CI.
.PHONY: install-build-deps
install-build-deps: install-lint-build-deps
ifeq ($(APT_PACKAGES),)
else ifeq ($(shell which apt-get),)
	$(warning Cannot install build dependencies without apt.)
	$(warning Please ensure the equivalents to these packages are installed: $(APT_PACKAGES))
else
	sudo $(APT) install $(APT_PACKAGES)
endif

# If additional build dependencies need installing in order to build the linting env.
.PHONY: install-lint-build-deps
install-lint-build-deps:
