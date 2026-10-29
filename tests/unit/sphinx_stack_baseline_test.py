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

"""Unit tests for the Sphinx Stack baseline helper's wiring.

Offline, like the baseline unit tests: the checkout's origin is a local
bare mirror whose path normalizes to the conf.py's ``github_url`` slug, so
remote matching, fetching, and branch resolution never touch the network.
Both branch-head baselines are pre-seeded, so the tests exercise the
helper's caching and branch routing without a collection build; the docs
dir has no Makefile, so any collection the caching fails to prevent fails
the test loudly.
"""

import json
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest
from sphinx_linkcheck_diff import baseline, sphinx_stack_baseline


class Checkout(NamedTuple):
    """A synthetic Sphinx Stack checkout with pre-seeded baselines.

    :param docs: the docs directory the helper runs in.
    :param main_sha: the head SHA of the default branch, ``main``.
    :param feature_sha: the head SHA of ``feature-branch``.
    """

    docs: Path
    main_sha: str
    feature_sha: str


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )
    return result.stdout


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    conf = (
        "html_context = {\n"
        '    "github_url": "https://github.com/canonical/example",\n'
        '    "repo_default_branch": "main",\n'
        "}\n"
    )
    seed = tmp_path / "seed"
    (seed / "docs").mkdir(parents=True)
    _run("git", "init", "-b", "main", cwd=seed)
    _run("git", "config", "user.name", "linkcheck-diff tests", cwd=seed)
    _run("git", "config", "user.email", "tests@example.com", cwd=seed)
    (seed / "docs" / "conf.py").write_text(conf, encoding="utf-8")
    _run("git", "add", "docs", cwd=seed)
    _run("git", "commit", "--quiet", "--message", "conf", cwd=seed)
    feature_sha = _run("git", "rev-parse", "HEAD", cwd=seed).strip()
    _run("git", "branch", "feature-branch", cwd=seed)
    (seed / "docs" / "index.md").write_text("# Example\n", encoding="utf-8")
    _run("git", "add", "docs", cwd=seed)
    _run("git", "commit", "--quiet", "--message", "index", cwd=seed)
    main_sha = _run("git", "rev-parse", "HEAD", cwd=seed).strip()

    # The mirror's path ends in ":canonical/example", which normalizes to
    # the same slug as the conf.py's github_url, so the helper's remote
    # matching, fetch, and resolution all stay offline.
    mirror = tmp_path / "mirror:canonical/example"
    _run("git", "clone", "--quiet", "--bare", str(seed), str(mirror))
    work = tmp_path / "work"
    _run("git", "clone", "--quiet", str(mirror), str(work))

    docs = work / "docs"
    for sha in (main_sha, feature_sha):
        path = baseline.baseline_path(docs, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"base_sha": sha, "uris": []}), encoding="utf-8")
    return Checkout(docs, main_sha, feature_sha)


def test_sphinx_stack_baseline(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout.docs)
    monkeypatch.delenv("BASE_BRANCH", raising=False)
    path = sphinx_stack_baseline()
    assert path == baseline.baseline_path(checkout.docs, checkout.main_sha)
    assert capsys.readouterr().out.strip() == str(path)


def test_sphinx_stack_baseline_base_branch(checkout, monkeypatch):
    monkeypatch.chdir(checkout.docs)
    monkeypatch.setenv("BASE_BRANCH", "feature-branch")
    path = sphinx_stack_baseline()
    assert path == baseline.baseline_path(checkout.docs, checkout.feature_sha)


def test_sphinx_stack_baseline_missing_baseline(checkout, monkeypatch):
    # A missing baseline triggers collection, and a collection failure
    # propagates: the synthetic docs dir has no Makefile.
    monkeypatch.chdir(checkout.docs)
    monkeypatch.delenv("BASE_BRANCH", raising=False)
    baseline.baseline_path(checkout.docs, checkout.main_sha).unlink()
    with pytest.raises(RuntimeError, match="make install failed"):
        sphinx_stack_baseline()
