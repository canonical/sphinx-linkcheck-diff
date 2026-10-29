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

"""Collect a linkcheck baseline from a base branch.

These helpers carry the Canonical Sphinx Stack's defaults: the
``install`` and ``linkcheck`` Makefile targets the collection driver
runs and the ``_build/output.json`` it reads. The policy on top is
``sphinx_stack_baseline``. A project whose docs build differently adapts
a copy of that module.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from sphinx.util.tags import Tags

FETCH_TIMEOUT = 30  # Seconds before falling back to the last fetched refs.


def repo_root(docs_dir: Path) -> Path:
    """Return the root of the repository containing ``docs_dir``."""
    return Path(_git("rev-parse", "--show-toplevel", cwd=docs_dir).strip())


def html_context(conf_path: Path) -> dict[str, Any]:
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
    context: dict[str, Any] = namespace["html_context"]
    return context


def setting(html_context: dict[str, Any], name: str) -> str:
    """Return a required string value from ``html_context``."""
    value = html_context.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set in html_context in docs/conf.py")
    return str(value)


def matching_remote(repo_root: Path, github_url: str) -> str:
    """Return the name of the git remote whose URL matches ``github_url``."""
    slug = _repo_slug(github_url)
    # git remote -v lists a fetch and a push line per remote; either can match.
    remotes: dict[str, str] = {}
    for line in _git("remote", "-v", cwd=repo_root).splitlines():
        name, url = line.split("\t", 1)
        url = url.removesuffix(" (fetch)").removesuffix(" (push)")
        remotes.setdefault(name, url)
        if _repo_slug(url) == slug:
            return name
    listed = ", ".join(f"{name} ({url})" for name, url in remotes.items())
    raise RuntimeError(
        f"no git remote matches github_url {github_url} (configured remotes:"
        f" {listed or 'none'}); add one with:"
        f" git remote add upstream https://github.com/{slug}"
    )


def fetch(remote: str, repo_root: Path) -> None:
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


def base_sha(repo_root: Path, remote: str, branch: str) -> str:
    """Return the head SHA of ``remote``'s ``branch``."""
    return _git("rev-parse", f"{remote}/{branch}", cwd=repo_root).strip()


@contextlib.contextmanager
def worktree(repo_root: Path, sha: str) -> Iterator[Path]:
    """Yield a detached worktree of ``sha``, removing it and its files afterwards."""
    tmp = Path(tempfile.mkdtemp(prefix=".linkcheck-diff-"))
    tree = tmp / "base"
    try:
        _git("worktree", "add", "--detach", str(tree), sha, cwd=repo_root)
        yield tree
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)


def make(
    target: str,
    cwd: Path,
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Makefile target and return the completed process.

    With ``check``, dump the target's output and raise on failure. ``env``
    replaces the process environment, as in ``subprocess.run``.
    """
    result = subprocess.run(
        ["make", target],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise RuntimeError(f"make {target} failed in {cwd}")
    return result


def parse_uris(output_json: Path) -> list[str]:
    """Return the URIs of a linkcheck ``output.json``, one JSON object per line.

    The URIs are in linkcheck's order, one per (document, URI) pair, so a URI
    referenced from several documents appears several times.
    """
    lines = output_json.read_text(encoding="utf-8").splitlines()
    return [str(json.loads(line)["uri"]) for line in lines if line]


def collect(repo_root: Path, docs_dir: Path, sha: str, sphinx_opts: str) -> list[str]:
    """Collect the base branch's URIs by building its docs in a temporary worktree.

    :param repo_root: path of the repository root.
    :param docs_dir: docs directory, relative to the repository root.
    :param sha: base head SHA to collect.
    :param sphinx_opts: forwarded ``SPHINX_OPTS`` for the collection build.
    :returns: the URIs of the base branch, in linkcheck's output order.
    """
    with worktree(repo_root, sha) as tree:
        docs = tree / docs_dir
        make("install", docs)
        opts = " ".join(
            part for part in (sphinx_opts, "-D linkcheck_ignore=.*") if part
        )
        build = make(
            "linkcheck",
            docs,
            check=False,
            env={**os.environ, "SPHINX_OPTS": opts},
        )
        output_json = docs / "_build" / "output.json"
        if not output_json.is_file():
            sys.stderr.write(build.stdout + build.stderr)
            raise RuntimeError(f"make linkcheck produced no {output_json}")
        return parse_uris(output_json)


def baseline_path(docs_dir: Path, sha: str) -> Path:
    """Return the cache path of ``sha``'s baseline under ``docs_dir``."""
    return docs_dir / "_dev" / ".linkcheck-diff" / "baselines" / f"{sha}.json"


def write_baseline(path: Path, sha: str, uris: list[str]) -> None:
    """Write ``uris`` as the baseline of ``sha`` to ``path``.

    The URIs are deduplicated and sorted.
    """
    baseline = {
        "base_sha": sha,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "uris": sorted(set(uris)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")


def _repo_slug(url: str) -> str:
    """Normalize a GitHub HTTPS or SSH URL to an ``owner/repo`` slug."""
    url = url.strip().rstrip("/").removesuffix(".git")
    if "://" in url:
        url = url.split("://", 1)[1]
        url = url.split("/", 1)[1] if "/" in url else ""
    elif ":" in url:
        url = url.split(":", 1)[1]
    return url


def _git(*args: str, cwd: Path) -> str:
    """Run a git command and return its stdout, raising on failure."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout
