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
requires (``github_url`` and ``repo_default_branch``), the Makefile targets
it runs (``install`` and ``linkcheck``), and where the build writes
``output.json``. A project that builds its docs differently copies only this
module into ``docs/_dev/`` and adapts the policy.
"""

import os
import sys
from pathlib import Path
from typing import Any

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

    github_url = _setting(html_context, "github_url")
    branch = _setting(html_context, "repo_default_branch")

    remote = baseline.matching_remote(repo_root, github_url)
    baseline.fetch(remote, repo_root)
    sha = baseline.base_sha(repo_root, remote, branch)

    baseline_path = baseline.baseline_path(docs_dir, sha)
    if not baseline_path.is_file():
        uris = _collect(repo_root, docs_dir.relative_to(repo_root), sha, sphinx_opts)
        baseline.write_baseline(baseline_path, sha, uris)

    print(baseline_path)
    return baseline_path


def _collect(repo_root: Path, docs_dir: Path, sha: str, sphinx_opts: str) -> list[str]:
    """Collect the base branch's URIs by building its docs in a temporary worktree.

    :param repo_root: path of the repository root.
    :param docs_dir: docs directory, relative to the repository root.
    :param sha: base head SHA to collect.
    :param sphinx_opts: forwarded ``SPHINX_OPTS`` for the collection build.
    :returns: the URIs of the base branch, in linkcheck's output order.
    """
    with baseline.worktree(repo_root, sha) as worktree:
        docs = worktree / docs_dir
        baseline.make("install", docs)
        opts = " ".join(
            part for part in (sphinx_opts, "-D linkcheck_ignore=.*") if part
        )
        build = baseline.make(
            "linkcheck",
            docs,
            check=False,
            env={**os.environ, "SPHINX_OPTS": opts},
        )
        output_json = docs / "_build" / "output.json"
        if not output_json.is_file():
            sys.stderr.write(build.stdout + build.stderr)
            raise RuntimeError(f"make linkcheck produced no {output_json}")
        return baseline.parse_uris(output_json)


def _setting(html_context: dict[str, Any], name: str) -> str:
    """Return a required string value from ``html_context``."""
    value = html_context.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set in html_context in docs/conf.py")
    return str(value)
