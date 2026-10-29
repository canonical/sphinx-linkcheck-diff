# sphinx-linkcheck-diff

<!-- Answer elevator-pitch questions about the extension – What is it? What does it do? What
essential problem does it solve? -->

sphinx-linkcheck-diff adds a Sphinx directive that generates a custom greeting.

## Basic usage

<!-- Provide a few examples of the extension's most common use cases. Remember the Pareto
principle! -->

To generate a greeting, add the `hello` directive to your document:

```
.. hello:: world!
```

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

© 2026 Canonical Ltd.
