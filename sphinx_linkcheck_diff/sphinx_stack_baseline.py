# This file is part of sphinx-ext-template.
#
# Copyright 2025 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License version 3, as published by the Free
# Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranties of MERCHANTABILITY, SATISFACTORY
# QUALITY, or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.

"""Collect a baseline of the base branch's URIs for restricted link checking.

This module is the Canonical Sphinx Stack policy on top of the
``sphinx_linkcheck_diff.baseline`` library: the ``html_context`` values it
requires (``github_url`` and ``repo_default_branch``). Everything else,
including the collection driver with the Stack's Makefile targets and
``output.json`` location, is a library function. A project that builds its
docs differently copies only this module into ``docs/_dev/``, adapts the
wiring, and defines module-local versions of any library function whose
defaults don't fit.
"""

from pathlib import Path

from . import baseline


def sphinx_stack_baseline(sphinx_opts: str = "") -> Path:
    """Return the path of the base branch's baseline, collecting it if needed.

    The baseline lists every URI the base branch's docs would check. It is
    cached per base SHA under ``_dev/.linkcheck-diff/baselines`` in the docs
    directory (the current working directory). The path is printed to stdout,
    which is how the Makefile target captures it.

    :param sphinx_opts: the project's ``SPHINX_OPTS``, forwarded to the
        collection build so it runs under the same settings.
    :returns: the path of the baseline file.
    """
    docs_dir = Path.cwd()
    repo_root = baseline.repo_root(docs_dir)
    html_context = baseline.html_context(docs_dir / "conf.py")

    github_url = baseline.setting(html_context, "github_url")
    branch = baseline.setting(html_context, "repo_default_branch")

    remote = baseline.matching_remote(repo_root, github_url)
    baseline.fetch(remote, repo_root)
    sha = baseline.base_sha(repo_root, remote, branch)

    baseline_path = baseline.baseline_path(docs_dir, sha)
    if not baseline_path.is_file():
        uris = baseline.collect(
            repo_root, docs_dir.relative_to(repo_root), sha, sphinx_opts
        )
        baseline.write_baseline(baseline_path, sha, uris)

    print(baseline_path)
    return baseline_path
