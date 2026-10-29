# This file is part of sphinx-linkcheck-diff.
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
``sphinx_linkcheck_diff.baseline`` library: it provides the entry point
the Makefile target runs. The base branch is ``BASE_BRANCH`` when set,
``repo_default_branch`` otherwise, and every setting it reads
(``repo_default_branch``, ``github_url``) comes from the docs
``html_context``. A project whose docs build differently copies this
module into ``docs/_dev/`` and defines module-local versions of the
library helpers whose defaults don't fit.
"""

import os
from pathlib import Path

from . import baseline


def sphinx_stack_baseline(sphinx_opts: str = "") -> Path:
    """Return the path of the base branch's baseline, collecting it if needed.

    The baseline lists every URI the base branch's docs would check. It is
    cached under ``_dev/.linkcheck-diff/baselines`` in the docs directory
    (the current working directory). The path is printed to stdout for the
    Makefile target to capture.

    :param sphinx_opts: the project's ``SPHINX_OPTS``, forwarded to the
        collection build so it runs under the same settings.
    """
    docs_dir = Path.cwd()
    repo_root = baseline.repo_root(docs_dir)
    html_context = baseline.html_context(docs_dir / "conf.py")

    github_url = baseline.setting(html_context, "github_url")
    branch = os.environ.get("BASE_BRANCH", "")
    if not branch:
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
