# sphinx-linkcheck-diff

<!-- Answer elevator-pitch questions about the extension – What is it? What does it do? What
essential problem does it solve? -->

sphinx-linkcheck-diff adds a `linkcheck-diff` Makefile target to Sphinx Stack
projects: it runs Sphinx's linkcheck build restricted to the links that are new
or changed relative to the project's base branch.

## Basic usage

<!-- Provide a few examples of the extension's most common use cases. Remember the Pareto
principle! -->

To adopt it in a project's docs, add the package to `docs/requirements.txt`,
add `sphinx_linkcheck_diff` to the `extensions` list in `conf.py`, and add the
`linkcheck-diff` target to the docs Makefile. Then run:

```bash
make linkcheck-diff
```

The first run collects the base branch's links as a baseline; later runs check
only new or changed links against the network.

## Project setup

<!-- Provide the simplest way to install the extension. In most cases, this will
be via `pip`. -->

sphinx-linkcheck-diff is published on PyPI and can be installed with:

```bash
pip install sphinx-linkcheck-diff
```

After adding sphinx-linkcheck-diff to your Python project, update your conf.py file to include
sphinx-linkcheck-diff as one of its extensions:

```python
extensions = [
    "sphinx_linkcheck_diff"
]
```

## Community and support

<!-- This is boilerplate. Replace the extension name and GitHub link. -->

You can report any issues or bugs on the project's [GitHub
repository](https://github.com/canonical/sphinx-ext-template).

sphinx-linkcheck-diff is covered by the [Ubuntu Code of
Conduct](https://ubuntu.com/community/ethos/code-of-conduct).

## License and copyright

<!-- Replace the extension name and, if necessary, the extension's license. -->

sphinx-linkcheck-diff is released under the [GPL-3.0 license](LICENSE).

© 2025 Canonical Ltd.
