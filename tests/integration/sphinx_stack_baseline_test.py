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

"""Integration tests for the Sphinx Stack baseline collection helper."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]

# The Stack's default SPHINX_OPTS (docs/Makefile), forwarded to the collect
# build so it runs under the same settings as the project's real build.
SPHINX_OPTS = "-c . -d _dev/.doctrees -j auto"

# Reference projects, pinned to their branch heads as of 2026-10-21. To move a
# pin, update the SHA here and regenerate the expected URI set in
# tests/integration/sphinx_stack_baseline/.
PROJECTS = {
    "sphinx-stack-docs": ("main", "36a13bc810755ea0d672ceefb7230da963423b54"),
    "jubilant": ("main", "15103ef6039e596d4c236802fa110b43d0a8d106"),
    "pebble": ("master", "26a687d0cf37ceb685f0e1daf2ff5296dc156736"),
}


def _run(*args: str, cwd: Path | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )


def _baseline(docs: Path) -> Path:
    """Run the helper in ``docs`` and return the baseline path it prints.

    The Makefile recipe sources the docs venv and runs the helper with its
    python3, capturing the printed path; that venv is also where the project's
    conf.py imports resolve. The project venvs don't install
    sphinx-linkcheck-diff, so the helper runs from this source tree.
    """
    code = (
        "import sys\n"
        "from sphinx_linkcheck_diff import sphinx_stack_baseline\n"
        "sphinx_stack_baseline(sys.argv[1])\n"
    )
    result = subprocess.run(
        [str(docs / ".venv" / "bin" / "python3"), "-c", code, SPHINX_OPTS],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        cwd=docs,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return Path(result.stdout.strip())


def _pinned_docs(repo: str, branch: str, sha: str, tmp_path: Path) -> Path:
    """Return the docs dir of a clone of ``repo`` with ``branch`` at ``sha``.

    The helper fetches the remote matching ``github_url`` and resolves
    ``origin/<branch>``, so the pin must live in the clone's own origin: a
    local bare mirror of a fresh GitHub clone with its branch ref pointed at
    ``sha``. The mirror's path ends in ``:canonical/<repo>``, which normalizes
    to the same slug as the project's ``github_url``, so the helper's remote
    matching, fetch, and resolution all stay local and land on the pin.
    """
    seed = tmp_path / "seed"
    _run("git", "clone", "--quiet", f"https://github.com/canonical/{repo}", str(seed))
    mirror = tmp_path / f"mirror:canonical/{repo}"
    _run("git", "clone", "--quiet", "--bare", str(seed), str(mirror))
    _run("git", "--git-dir", str(mirror), "update-ref", f"refs/heads/{branch}", sha)
    work = tmp_path / "work"
    _run("git", "clone", "--quiet", str(mirror), str(work))
    if repo == "sphinx-stack-docs":
        # The template project's conf.py predates repo_default_branch, which
        # the helper requires. The patch only affects the conf.py the helper
        # reads: the collection worktree builds the committed conf.py.
        conf = work / "docs" / "conf.py"
        conf.write_text(
            conf.read_text() + '\nhtml_context["repo_default_branch"] = "main"\n',
            encoding="utf-8",
        )
    docs = work / "docs"
    _run("make", "install", cwd=docs)
    return docs


@pytest.mark.slow
@pytest.mark.parametrize(
    ("repo", "branch", "sha"),
    [(name, branch, sha) for name, (branch, sha) in PROJECTS.items()],
)
def test_sphinx_stack_baseline(repo, branch, sha, tmp_path):
    docs = _pinned_docs(repo, branch, sha, tmp_path)
    baseline = _baseline(docs)

    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert baseline.name == f"{sha}.json"
    assert data["base_sha"] == sha

    fixture = Path(__file__).parent / "sphinx_stack_baseline" / f"{repo}.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    assert expected["base_sha"] == sha
    assert data["uris"] == expected["uris"]
