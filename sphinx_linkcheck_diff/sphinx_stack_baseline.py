# This file is part of sphinx-linkcheck-diff.
#
# Copyright 2026 Canonical Ltd.
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

"""Collect a baseline of the base branch's URIs for restricted link checking."""

# Apply this module as-is if your docs build matches the Canonical Sphinx
# Stack: a Makefile with ``install`` and ``linkcheck`` targets, and
# ``github_url`` and ``repo_default_branch`` set in the docs
# ``html_context``. The linkcheck-diff target runs it with
# ``python -m sphinx_linkcheck_diff``.
#
# If your project builds its docs differently, vendor this module: copy it
# into ``docs/_dev/``, swap the relative ``baseline`` import for the
# installed package's, adjust the ``html_context`` values it reads, and
# point the Makefile recipe at the copy.

import os
import sys
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


def main() -> None:
    """Run the collection helper, reporting failures as single lines."""
    sphinx_opts = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        sphinx_stack_baseline(sphinx_opts)
    except RuntimeError as exc:
        print(f"linkcheck-diff: {exc}", file=sys.stderr)
        sys.exit(1)


# A vendored copy runs as a script: ``python3 _dev/sphinx_stack_baseline.py``.
# This guard is what makes that work. The installed package runs the same
# ``main()`` with ``python -m sphinx_linkcheck_diff``.
if __name__ == "__main__":
    main()
