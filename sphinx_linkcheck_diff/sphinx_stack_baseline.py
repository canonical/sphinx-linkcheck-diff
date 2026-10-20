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

The helper is specific to the Canonical Sphinx Stack: it assumes the Stack's
``docs/Makefile`` targets (``install`` and ``linkcheck``) and the standard
``html_context`` values (``github_url`` and ``repo_default_branch``).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sphinx.util.tags import Tags

FETCH_TIMEOUT = 30  # Seconds before falling back to the last fetched refs.


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
    repo_root = Path(_git("rev-parse", "--show-toplevel", cwd=docs_dir).strip())
    html_context = _html_context(docs_dir / "conf.py")

    remote = _matching_remote(repo_root, _setting(html_context, "github_url"))
    branch = _setting(html_context, "repo_default_branch")

    _fetch(remote, repo_root)
    sha = _git("rev-parse", f"{remote}/{branch}", cwd=repo_root).strip()

    baseline_path = docs_dir / "_dev" / ".linkcheck-diff" / "baselines" / f"{sha}.json"
    if not baseline_path.is_file():
        uris = _collect(repo_root, docs_dir.relative_to(repo_root), sha, sphinx_opts)
        baseline = {
            "base_sha": sha,
            "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "uris": sorted(uris),
        }
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
        )

    print(baseline_path)
    return baseline_path


def _collect(repo_root: Path, docs_dir: Path, sha: str, sphinx_opts: str) -> list[str]:
    """Collect the base branch's URIs by building its docs in a temporary worktree.

    :param repo_root: path of the repository root.
    :param docs_dir: docs directory, relative to the repository root.
    :param sha: base head SHA to collect.
    :param sphinx_opts: forwarded ``SPHINX_OPTS`` for the collection build.
    :returns: the sorted URIs of the base branch.
    """
    tmp = Path(tempfile.mkdtemp(prefix=".linkcheck-diff-"))
    worktree = tmp / "base"
    try:
        _git("worktree", "add", "--detach", str(worktree), sha, cwd=repo_root)
        docs = worktree / docs_dir
        _make("install", docs)
        opts = " ".join(
            part for part in (sphinx_opts, "-D linkcheck_ignore=.*") if part
        )
        build = subprocess.run(
            ["make", "linkcheck"],
            cwd=docs,
            env={**os.environ, "SPHINX_OPTS": opts},
            capture_output=True,
            text=True,
            check=False,
        )
        output_json = docs / "_build" / "output.json"
        if not output_json.is_file():
            sys.stderr.write(build.stdout + build.stderr)
            raise RuntimeError(f"make linkcheck produced no {output_json}")
        return _parse_uris(output_json)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)


def _html_context(conf_path: Path) -> dict[str, Any]:
    """Execute the docs ``conf.py`` and return its ``html_context``."""
    if not conf_path.is_file():
        raise RuntimeError(
            f"no conf.py at {conf_path}; run the helper from the docs directory"
        )
    namespace: dict[str, Any] = {
        "__file__": str(conf_path),
        "tags": Tags(),
    }
    exec(compile(conf_path.read_bytes(), str(conf_path), "exec"), namespace)  # noqa: S102
    if "html_context" not in namespace:
        raise RuntimeError(f"no html_context in {conf_path}")
    html_context: dict[str, Any] = namespace["html_context"]
    return html_context


def _matching_remote(repo_root: Path, github_url: str) -> str:
    """Return the name of the git remote whose URL matches ``github_url``."""
    slug = _repo_slug(github_url)
    for line in _git("remote", "-v", cwd=repo_root).splitlines():
        name, url = line.split("\t", 1)
        if _repo_slug(url.removesuffix(" (fetch)").removesuffix(" (push)")) == slug:
            return name
    raise RuntimeError(f"no git remote matches github_url {github_url}")


def _repo_slug(url: str) -> str:
    """Normalize a GitHub HTTPS or SSH URL to an ``owner/repo`` slug."""
    url = url.strip().rstrip("/").removesuffix(".git")
    if "://" in url:
        url = url.split("://", 1)[1]
        url = url.split("/", 1)[1] if "/" in url else ""
    elif ":" in url:
        url = url.split(":", 1)[1]
    return url


def _setting(html_context: dict[str, Any], name: str) -> str:
    """Return a required string value from ``html_context``."""
    value = html_context.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set in html_context in docs/conf.py")
    return str(value)


def _fetch(remote: str, repo_root: Path) -> None:
    """Fetch the remote, warning to stderr on failure so cached refs can be used."""
    try:
        subprocess.run(
            ["git", "fetch", "--quiet", remote],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT,
            check=True,
        )
    except subprocess.TimeoutExpired:
        print(
            f"linkcheck-diff: git fetch {remote} timed out after"
            f" {FETCH_TIMEOUT} seconds;"
            " continuing with the refs from the last successful fetch",
            file=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"linkcheck-diff: git fetch {remote} failed; continuing with the refs"
            f" from the last successful fetch:\n{exc.stderr or ''}",
            file=sys.stderr,
        )


def _make(target: str, cwd: Path) -> None:
    """Run a Makefile target, dumping its output and raising on failure."""
    result = subprocess.run(
        ["make", target], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise RuntimeError(f"make {target} failed in {cwd}")


def _parse_uris(output_json: Path) -> list[str]:
    """Return the sorted URIs of a linkcheck ``output.json`` (JSONL)."""
    lines = output_json.read_text(encoding="utf-8").splitlines()
    return sorted({str(json.loads(line)["uri"]) for line in lines if line})


def _git(*args: str, cwd: Path) -> str:
    """Run a git command and return its stdout, raising on failure."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout
