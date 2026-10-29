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

"""Functional tests for the baseline filter extension.

Each test builds a throwaway Sphinx project in-process. The broken URI
points at a closed port on localhost, and the baseline filter skips
covered URIs before Sphinx makes any request, so no test reaches
beyond localhost.
"""

import json
from pathlib import Path

import pytest
from sphinx.application import Sphinx
from sphinx.errors import ExtensionError

BROKEN_URI = "http://127.0.0.1:1/broken"
COVERED_URI = "https://example.com/covered"


def _write_project(
    tmp_path: Path, baseline: str = "", uris: tuple[str, ...] = ()
) -> None:
    """Write a one-page Sphinx project that uses the extension.

    The page links each URI in ``uris``. A URI the baseline file
    doesn't cover is requested during the build, so every uncovered
    URI must be ``BROKEN_URI``: its connection is refused offline.
    """
    (tmp_path / "conf.py").write_text(
        "extensions = ['sphinx_linkcheck_diff']\n"
        f"linkcheck_diff_baseline = {baseline!r}\n"
        "master_doc = 'index'\n",
        encoding="utf-8",
    )
    links = "\n".join(f"* `{uri} <{uri}>`_" for uri in uris)
    (tmp_path / "index.rst").write_text(
        f"Home\n====\n\n{links}\n",
        encoding="utf-8",
    )


def _write_baseline(tmp_path: Path, uris: list[str]) -> str:
    """Write a baseline file listing ``uris``, and return its path."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"uris": uris}), encoding="utf-8")
    return str(path)


def _build_app(tmp_path: Path, buildername: str = "linkcheck") -> Sphinx:
    return Sphinx(
        srcdir=str(tmp_path),
        confdir=str(tmp_path),
        outdir=str(tmp_path / "_build" / buildername),
        doctreedir=str(tmp_path / "_build" / ".doctrees"),
        buildername=buildername,
        status=None,
        warning=None,
    )


def _output_statuses(tmp_path: Path, buildername: str = "linkcheck") -> dict[str, str]:
    """Return each output.json URI with its status, keyed by URI."""
    output = tmp_path / "_build" / buildername / "output.json"
    lines = output.read_text(encoding="utf-8").splitlines()
    entries = (json.loads(line) for line in lines if line)
    return {entry["uri"]: entry["status"] for entry in entries}


def test_covered_uri_ignored_broken_uri_reported(tmp_path: Path):
    """The baseline URI is skipped; the broken URI fails the build."""
    _write_project(
        tmp_path,
        _write_baseline(tmp_path, [COVERED_URI]),
        (COVERED_URI, BROKEN_URI),
    )

    app = _build_app(tmp_path)
    app.build()

    statuses = _output_statuses(tmp_path)
    assert statuses[COVERED_URI] == "ignored"
    assert statuses[BROKEN_URI] == "broken"
    assert app.statuscode == 1


def test_all_uris_covered_build_passes(tmp_path: Path):
    """With every URI covered, the build passes: nothing new or changed."""
    _write_project(
        tmp_path,
        _write_baseline(tmp_path, [COVERED_URI, BROKEN_URI]),
        (COVERED_URI, BROKEN_URI),
    )

    app = _build_app(tmp_path)
    app.build()

    assert _output_statuses(tmp_path) == {
        COVERED_URI: "ignored",
        BROKEN_URI: "ignored",
    }
    assert app.statuscode == 0


def test_html_build_untouched(tmp_path: Path):
    """A baseline applies only to linkcheck: an html build ignores it."""
    baseline = _write_baseline(tmp_path, [COVERED_URI])
    _write_project(tmp_path, baseline)

    app = _build_app(tmp_path, buildername="html")
    app.build()

    # The handler is dormant for non-linkcheck builders: nothing is read.
    assert app.config.linkcheck_ignore == []
    assert (app.outdir / "index.html").is_file()


def test_empty_baseline_reports_all(tmp_path: Path):
    """An empty ``linkcheck_diff_baseline`` disables the filter."""
    _write_project(tmp_path, uris=(BROKEN_URI,))

    app = _build_app(tmp_path)
    app.build()

    assert _output_statuses(tmp_path)[BROKEN_URI] == "broken"
    assert app.statuscode == 1


def test_missing_baseline_fails_build(tmp_path: Path):
    """A baseline path that doesn't exist fails the build."""
    _write_project(tmp_path, str(tmp_path / "absent.json"))

    with pytest.raises(ExtensionError, match="can't read baseline"):
        _build_app(tmp_path)


def test_not_a_baseline_fails_build(tmp_path: Path):
    """A baseline file that holds other JSON fails the build."""
    path = tmp_path / "baseline.json"
    path.write_text("[]", encoding="utf-8")
    _write_project(tmp_path, str(path))

    with pytest.raises(ExtensionError, match="has no uris list"):
        _build_app(tmp_path)
