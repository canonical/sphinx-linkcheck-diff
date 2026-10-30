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

"""Functional tests for the Sphinx Stack baseline collection helper."""

import json
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).parents[2]

# The Stack's default SPHINX_OPTS (the docs Makefile), except -j: with parallel
# reads Sphinx merges each chunk's domain data in completion order, and
# cross-reference resolution picks from that order, so which page a
# reference resolves to — and therefore which anchors linkcheck collects —
# varies with the machine's core count. A serial build reads documents in
# sorted order and collects the same set on every machine.
SPHINX_OPTS = "-c . -d _dev/.doctrees -j 1"


class Project(NamedTuple):
    """A reference project the tests collect a baseline from.

    :param branch: the branch the clone checks out, pinned to ``sha``.
    :param sha: the pinned head of ``branch``.
    :param docs_dir: the docs directory the helper runs in. The Stack's
        convention is ``docs/``, but microcloud's docs live in ``doc/``.
    :param docs_python: the Python the docs venv is built with. autodoc
        introspects the project under that venv's interpreter, and the same
        typehint cross-reference can resolve to a different page — and so a
        different anchor — under a different interpreter, so the tests pin
        the interpreter: the repository's minimum Python for the Stack
        projects, and the 3.11 microcloud's docs requirements need.
    :param base_branch: the helper's ``BASE_BRANCH``: the branch whose
        baseline to collect, empty meaning the project's
        ``repo_default_branch``. microcloud's docs live on ``v3-edge``, but
        its conf.py names ``main`` as the default, so the tests must say so.
    """

    branch: str
    sha: str
    docs_dir: str = "docs"
    docs_python: str = "3.10"
    base_branch: str = ""


# Reference projects, pinned to branch heads: sphinx-stack-docs, jubilant,
# and pebble as of 2026-10-21, microcloud's v3-edge as of 2026-10-28. To move
# a pin, update the SHA here and regenerate the expected URI set in
# tests/functional/sphinx_stack_baseline/.
PROJECTS = {
    "sphinx-stack-docs": Project("main", "36a13bc810755ea0d672ceefb7230da963423b54"),
    "jubilant": Project("main", "15103ef6039e596d4c236802fa110b43d0a8d106"),
    "pebble": Project("master", "26a687d0cf37ceb685f0e1daf2ff5296dc156736"),
    "microcloud": Project(
        "v3-edge",
        "2c3a8bbd64b91f3943c1a17d1283b44ed500bbfa",
        docs_dir="doc",
        docs_python="3.11",
        base_branch="v3-edge",
    ),
}


def _run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    result = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )


def _pinned_env(docs_python: str) -> dict[str, str]:
    """Return the environment with a ``docs_python`` interpreter first on PATH.

    The Stack's Makefile builds the docs venv with whatever ``python3`` is
    first on PATH, so this is how the tests pin that venv's interpreter.
    ``uv python install`` downloads the interpreter when it's missing, as on
    a CI runner whose own Python is older.
    """
    _run("uv", "python", "install", docs_python)
    find = subprocess.run(
        ["uv", "python", "find", docs_python],
        capture_output=True,
        text=True,
        check=False,
    )
    if find.returncode != 0:
        raise AssertionError(
            f"uv python find {docs_python} failed:\n{find.stdout}{find.stderr}"
        )
    python = Path(find.stdout.strip())
    return {**os.environ, "PATH": f"{python.parent}{os.pathsep}{os.environ['PATH']}"}


def _baseline(docs: Path, project: Project) -> Path:
    """Run the helper in ``docs`` and return the baseline path it prints.

    The Makefile recipe sources the docs venv and runs the helper with `python
    -m sphinx_linkcheck_diff`, capturing the printed path; that venv is also
    where the project's conf.py imports resolve. The project venvs don't
    install sphinx-linkcheck-diff, so the helper runs from this source tree.
    ``BASE_BRANCH`` routes the helper to the project's base branch; empty
    means its ``repo_default_branch``.
    """
    result = subprocess.run(
        [
            str(docs / ".venv" / "bin" / "python3"),
            "-m",
            "sphinx_linkcheck_diff",
            SPHINX_OPTS,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **_pinned_env(project.docs_python),
            "PYTHONPATH": str(REPO_ROOT),
            "BASE_BRANCH": project.base_branch,
        },
        cwd=docs,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return Path(result.stdout.strip())


def _pinned_docs(repo: str, project: Project, tmp_path: Path) -> Path:
    """Return the docs dir of a clone of ``repo`` with its branch at ``sha``.

    The helper fetches the remote matching ``github_url`` and resolves the
    base branch — ``BASE_BRANCH``, or ``repo_default_branch`` — against it,
    so the pin must live in the clone's own origin: a local bare mirror of a
    fresh GitHub clone with its branch ref pointed at ``sha``. The mirror's
    path ends in ``:canonical/<repo>``, which normalizes to the same slug as
    the project's ``github_url``, so the helper's remote matching, fetch,
    and resolution all stay local and land on the pin. Every project's base
    branch is its checked-out branch, so the one pinned ref is also the base
    the helper resolves.
    """
    seed = tmp_path / "seed"
    _run("git", "clone", "--quiet", f"https://github.com/canonical/{repo}", str(seed))
    mirror = tmp_path / f"mirror:canonical/{repo}"
    _run("git", "clone", "--quiet", "--bare", str(seed), str(mirror))
    _run(
        "git",
        "--git-dir",
        str(mirror),
        "update-ref",
        f"refs/heads/{project.branch}",
        project.sha,
    )
    work = tmp_path / "work"
    # The mirror's HEAD is the GitHub default branch, not necessarily the
    # pinned branch, so the clone checks the branch out explicitly.
    _run("git", "clone", "--quiet", "--branch", project.branch, str(mirror), str(work))
    if repo == "sphinx-stack-docs":
        # The template project's conf.py predates repo_default_branch, which
        # the helper requires. The patch only affects the conf.py the helper
        # reads: the collection worktree builds the committed conf.py.
        conf = work / project.docs_dir / "conf.py"
        conf.write_text(
            conf.read_text() + '\nhtml_context["repo_default_branch"] = "main"\n',
            encoding="utf-8",
        )
    docs = work / project.docs_dir
    _run("make", "install", cwd=docs, env=_pinned_env(project.docs_python))
    return docs


@pytest.mark.slow
@pytest.mark.parametrize(
    ("repo", "project"), list(PROJECTS.items()), ids=list(PROJECTS)
)
def test_sphinx_stack_baseline(repo, project, tmp_path):
    docs = _pinned_docs(repo, project, tmp_path)
    baseline = _baseline(docs, project)

    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert baseline.name == f"{project.sha}.json"
    assert data["base_sha"] == project.sha

    fixture = Path(__file__).parent / "sphinx_stack_baseline" / f"{repo}.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    assert expected["base_sha"] == project.sha
    if data["uris"] != expected["uris"]:
        print(
            f"--- collected ({len(data['uris'])}) vs fixture ({len(expected['uris'])}) ---"
        )
        print(
            "docs venv:", (docs / ".venv" / "pip_list.txt").read_text(encoding="utf-8")
        )
        print("only collected:", sorted(set(data["uris"]) - set(expected["uris"])))
        print("only fixture:", sorted(set(expected["uris"]) - set(data["uris"])))
    assert data["uris"] == expected["uris"]
