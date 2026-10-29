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

"""Integration test of the linkcheck-diff Makefile target against jubilant's docs."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]

# jubilant's main as of 2026-10-21, the same pin as the functional tests.
JUBILANT_SHA = "15103ef6039e596d4c236802fa110b43d0a8d106"

# The Stack's default SPHINX_OPTS, except -j: with parallel reads Sphinx
# merges each chunk's domain data in completion order, so which page a
# reference resolves to — and so which anchors linkcheck collects — varies
# between builds. A serial build collects the same URIs every time, so the
# baseline covers the filtered build exactly.
SPHINX_OPTS = "-c . -d _dev/.doctrees -j 1"

# Connection-refused URIs, which linkcheck fails in milliseconds: its
# retry loop has no delay.
CHANGED_URI = "http://127.0.0.1:1/changed"
NEW_URI = "http://127.0.0.1:1/new"


def _run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run ``args``, raising with the output on failure."""
    result = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )


def _pinned_env() -> dict[str, str]:
    """Return the environment with a 3.10 interpreter first on PATH.

    The Stack's Makefile builds the docs venv with whatever ``python3``
    is first on PATH, so this is how the test pins that venv's
    interpreter: the repository's minimum Python, 3.10. ``uv python
    install`` downloads the interpreter when it's missing, as on a CI
    runner whose own Python is older.
    """
    _run("uv", "python", "install", "3.10")
    find = subprocess.run(
        ["uv", "python", "find", "3.10"],
        capture_output=True,
        text=True,
        check=False,
    )
    if find.returncode != 0:
        raise AssertionError(f"uv python find 3.10 failed:\n{find.stdout}{find.stderr}")
    python = Path(find.stdout.strip())
    return {**os.environ, "PATH": f"{python.parent}{os.pathsep}{os.environ['PATH']}"}


def _pinned_docs(tmp_path: Path) -> Path:
    """Return the docs dir of a jubilant clone with its main at the pin.

    The helper fetches the remote matching ``github_url`` and resolves the
    base branch against it, so the pin must live in the clone's own
    origin: a local bare mirror of a fresh GitHub clone with its main ref
    pointed at the pin. The mirror's path ends in ``:canonical/jubilant``,
    which normalizes to the same slug as the project's ``github_url``,
    so the helper's remote matching, fetch, and resolution all stay
    local and land on the pin.

    The clone lands on a feature branch: the test stands in for the
    contributor who branches off main to change the docs.
    """
    seed = tmp_path / "seed"
    _run("git", "clone", "--quiet", "https://github.com/canonical/jubilant", str(seed))
    mirror = tmp_path / "mirror:canonical/jubilant"
    _run("git", "clone", "--quiet", "--bare", str(seed), str(mirror))
    _run(
        "git",
        "--git-dir",
        str(mirror),
        "update-ref",
        "refs/heads/main",
        JUBILANT_SHA,
    )
    work = tmp_path / "work"
    _run("git", "clone", "--quiet", "--branch", "main", str(mirror), str(work))
    _run("git", "switch", "-c", "linkcheck-diff-trial", cwd=work)
    docs = work / "docs"
    shutil.copy(
        REPO_ROOT / "tests" / "integration" / "jubilant" / "conf.py",
        docs / "conf.py",
    )
    shutil.copy(
        REPO_ROOT / "tests" / "integration" / "jubilant" / "Makefile",
        docs / "Makefile",
    )
    _run("make", "install", cwd=docs, env=_pinned_env())
    return docs


def _entries(docs: Path) -> list[dict]:
    """Return linkcheck's output entries, one JSON object per line."""
    return [
        json.loads(line)
        for line in (docs / "_build" / "output.json")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def _broken_uris(docs: Path) -> list[str]:
    """Return the URIs with status ``broken`` in the linkcheck output."""
    return [entry["uri"] for entry in _entries(docs) if entry["status"] == "broken"]


def _make_linkcheck_diff(docs: Path) -> subprocess.CompletedProcess[str]:
    """Run ``make linkcheck-diff``, printing its output when it fails."""
    result = subprocess.run(
        ["make", "linkcheck-diff"],
        cwd=docs,
        env={**_pinned_env(), "SPHINX_OPTS": SPHINX_OPTS},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout + result.stderr)
    return result


def _install_package(docs: Path) -> None:
    """Install this repository's package into the docs venv."""
    _run(str(docs / ".venv" / "bin" / "pip"), "install", str(REPO_ROOT))


@pytest.mark.slow
def test_linkcheck_diff_finds_new_and_changed(tmp_path):
    """Run linkcheck-diff on a fresh branch, then with a changed and a new link.

    The first run stands in for a contributor who has branched off main
    and not touched the docs: every URI is in the baseline, so the filter
    ignores it and the build passes. The second run plants two broken
    links. The changed link's old URI is in the baseline, and the new
    link's URI is not, so both are checked and both fail. The build must
    fail with exactly those two URIs broken.
    """
    docs = _pinned_docs(tmp_path)
    _install_package(docs)

    build = _make_linkcheck_diff(docs)
    assert build.returncode == 0, "fresh branch off main reports no broken links"
    statuses = {entry["status"] for entry in _entries(docs)}
    assert statuses == {"ignored"}, "every URI on a fresh branch is in the baseline"

    page = docs / "tutorial" / "getting-started.md"
    text = page.read_text(encoding="utf-8")
    old_issue = "https://github.com/canonical/jubilant/issues/new"
    new_text = text.replace(old_issue, CHANGED_URI)
    new_text = new_text.rstrip() + f"\n\n[{old_issue}]({NEW_URI})\n"
    page.write_text(new_text, encoding="utf-8")

    build = _make_linkcheck_diff(docs)
    assert build.returncode != 0, "planted broken links: a changed one and a new one"
    assert sorted(_broken_uris(docs)) == [CHANGED_URI, NEW_URI]
