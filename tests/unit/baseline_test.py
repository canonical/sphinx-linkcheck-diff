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

"""Unit tests for the baseline library helpers.

These tests are offline: the git helpers run against temporary repositories
with local remotes and remote-tracking refs, never a network fetch. The
slow functional tests cover the collection driver end to end.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from sphinx_linkcheck_diff import baseline


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )
    return result.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Return the root of a git repository with one commit on ``main``."""
    root = tmp_path / "repo"
    root.mkdir()
    _run("git", "init", "-b", "main", cwd=root)
    _run("git", "config", "user.name", "linkcheck-diff tests", cwd=root)
    _run("git", "config", "user.email", "tests@example.com", cwd=root)
    (root / "file.txt").write_text("data\n", encoding="utf-8")
    _run("git", "add", "file.txt", cwd=root)
    _run("git", "commit", "--quiet", "--message", "initial", cwd=root)
    return root


def test_repo_root(git_repo: Path):
    docs = git_repo / "docs"
    docs.mkdir()
    assert baseline.repo_root(docs) == git_repo.resolve()


def test_html_context(tmp_path: Path):
    conf = tmp_path / "conf.py"
    conf.write_text(
        'html_context = {"github_url": "https://github.com/canonical/example"}\n',
        encoding="utf-8",
    )
    assert baseline.html_context(conf) == {
        "github_url": "https://github.com/canonical/example"
    }


def test_html_context_tags(tmp_path: Path):
    # A conf.py that calls tags.add() unguarded must execute (NOTES §1).
    conf = tmp_path / "conf.py"
    conf.write_text('tags.add("branch")\nhtml_context = {}\n', encoding="utf-8")
    assert baseline.html_context(conf) == {}


def test_html_context_no_conf_py(tmp_path: Path):
    with pytest.raises(RuntimeError, match="no conf.py"):
        baseline.html_context(tmp_path / "conf.py")


def test_html_context_no_html_context(tmp_path: Path):
    conf = tmp_path / "conf.py"
    conf.write_text("extensions = []\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no html_context"):
        baseline.html_context(conf)


def test_setting():
    context = {"github_url": "https://github.com/canonical/example"}
    assert (
        baseline.setting(context, "github_url")
        == "https://github.com/canonical/example"
    )


@pytest.mark.parametrize("context", [{}, {"github_url": ""}])
def test_setting_unset(context):
    with pytest.raises(RuntimeError, match="github_url is not set"):
        baseline.setting(context, "github_url")


@pytest.mark.parametrize(
    ("remote_url", "github_url"),
    [
        (
            "https://github.com/canonical/example",
            "https://github.com/canonical/example",
        ),
        (
            "https://github.com/canonical/example.git",
            "https://github.com/canonical/example",
        ),
        (
            "git@github.com:canonical/example.git",
            "https://github.com/canonical/example",
        ),
        (
            "https://github.com/canonical/example/",
            "https://github.com/canonical/example",
        ),
        ("https://github.com/canonical/example", "git@github.com:canonical/example"),
    ],
)
def test_matching_remote(git_repo: Path, remote_url: str, github_url: str):
    _run("git", "remote", "add", "origin", remote_url, cwd=git_repo)
    _run(
        "git",
        "remote",
        "add",
        "other",
        "https://github.com/canonical/other",
        cwd=git_repo,
    )
    assert baseline.matching_remote(git_repo, github_url) == "origin"


def test_matching_remote_no_match(git_repo: Path):
    _run(
        "git",
        "remote",
        "add",
        "origin",
        "https://github.com/canonical/other",
        cwd=git_repo,
    )
    with pytest.raises(RuntimeError) as excinfo:
        baseline.matching_remote(git_repo, "https://github.com/canonical/example")
    message = str(excinfo.value)
    assert "canonical/example" in message
    assert "origin" in message
    assert "git remote add" in message


def test_matching_remote_no_remotes(git_repo: Path):
    with pytest.raises(RuntimeError) as excinfo:
        baseline.matching_remote(git_repo, "https://github.com/canonical/example")
    assert "remotes: none" in str(excinfo.value)


def test_fetch_failure_warns(git_repo: Path, tmp_path: Path, capsys):
    # A failed fetch warns and continues instead of raising.
    _run("git", "remote", "add", "origin", str(tmp_path / "missing"), cwd=git_repo)
    baseline.fetch("origin", git_repo)
    assert "git fetch origin failed" in capsys.readouterr().err


def test_base_sha(git_repo: Path):
    sha = _run("git", "rev-parse", "HEAD", cwd=git_repo).strip()
    _run("git", "update-ref", "refs/remotes/origin/main", sha, cwd=git_repo)
    assert baseline.base_sha(git_repo, "origin", "main") == sha


def test_worktree(git_repo: Path):
    sha = _run("git", "rev-parse", "HEAD", cwd=git_repo).strip()
    with baseline.worktree(git_repo, sha) as tree:
        assert (tree / "file.txt").read_text(encoding="utf-8") == "data\n"
        tmp = tree.parent
    assert not tmp.exists()
    listing = _run("git", "worktree", "list", cwd=git_repo)
    assert str(tree) not in listing


def test_worktree_bad_sha(git_repo: Path):
    with pytest.raises(RuntimeError):
        with baseline.worktree(git_repo, "0" * 40):
            pass


def test_make(tmp_path: Path):
    (tmp_path / "Makefile").write_text(
        "ok:\n\ttouch file.txt\nfail:\n\texit 1\n", encoding="utf-8"
    )
    baseline.make("ok", cwd=tmp_path)
    assert (tmp_path / "file.txt").is_file()
    with pytest.raises(RuntimeError, match="make fail failed"):
        baseline.make("fail", cwd=tmp_path)


def test_parse_uris(tmp_path: Path):
    output_json = tmp_path / "output.json"
    output_json.write_text(
        '{"uri": "https://example.com/one"}\n'
        "\n"
        '{"uri": "https://example.com/two"}\n'
        '{"uri": "https://example.com/one"}\n',
        encoding="utf-8",
    )
    assert baseline.parse_uris(output_json) == [
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/one",
    ]


def test_baseline_path(tmp_path: Path):
    one = baseline.baseline_path(tmp_path, "abc123")
    two = baseline.baseline_path(tmp_path, "def456")
    assert one == tmp_path / "_dev" / ".linkcheck-diff" / "baselines" / "abc123.json"
    assert one != two


def test_write_baseline(tmp_path: Path):
    path = baseline.baseline_path(tmp_path, "abc123")
    baseline.write_baseline(
        path,
        "abc123",
        ["https://example.com/b", "https://example.com/a", "https://example.com/b"],
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_sha"] == "abc123"
    assert datetime.fromisoformat(data["collected_at"])
    assert data["uris"] == ["https://example.com/a", "https://example.com/b"]
