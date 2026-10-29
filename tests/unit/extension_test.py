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

"""Unit tests for the baseline filter extension.

These tests are offline: the handler is driven directly with a config
and builder stand-in, so no network and no document parsing. The slow
functional tests cover real Sphinx builds.
"""

import json
import re
from pathlib import Path
from typing import cast

import pytest
from sphinx.application import Sphinx
from sphinx.builders.linkcheck import CheckExternalLinksBuilder
from sphinx.errors import ExtensionError
from sphinx_linkcheck_diff import _extension

# ``/`` is not escaped by ``re.escape``, ``(`` and ``)`` are.
_BASELINE_URIS = ["https://example.com/docs", "https://example.com/(api)"]
_ESCAPED_URIS = [
    r"^https://example\.com/docs$",
    r"^https://example\.com/\(api\)$",
]


class _FakeBuilder:
    """Stand in for a non-linkcheck builder such as ``html``."""


class _FakeConfig:
    """Carry the two values the handler reads."""

    def __init__(self, baseline: str = "", ignore: list[str] | None = None) -> None:
        self.linkcheck_diff_baseline = baseline
        self.linkcheck_ignore = ignore if ignore is not None else []


class _FakeApp:
    """Carry only what the handler reads: ``builder`` and ``config``."""

    def __init__(self, builder: object, config: _FakeConfig) -> None:
        self.builder = builder
        self.config = config


def _linkcheck_instance() -> CheckExternalLinksBuilder:
    """Return a linkcheck builder instance.

    The real ``__init__`` needs a full app and environment, but the
    handler only asks the builder for its type, so skipping ``__init__``
    leaves everything the test needs.
    """
    return CheckExternalLinksBuilder.__new__(CheckExternalLinksBuilder)


def _app(
    builder: object = None, baseline: str = "", ignore: list[str] | None = None
) -> Sphinx:
    """Return an app stand-in cast to ``Sphinx``.

    The cast is safe for the same reason the stand-in is: the handler
    reads only ``builder`` and ``config``.
    """
    return cast(
        Sphinx,
        _FakeApp(builder=builder, config=_FakeConfig(baseline, ignore)),
    )


@pytest.fixture
def baseline_path(tmp_path: Path) -> Path:
    """Return a baseline file listing two URIs."""
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"base_sha": "a1b2c3d", "uris": _BASELINE_URIS}),
        encoding="utf-8",
    )
    return path


def test_ignores_baseline_uris(baseline_path: Path):
    app = _app(
        builder=_linkcheck_instance(),
        baseline=str(baseline_path),
        ignore=[".*bad.*"],
    )

    _extension._ignore_baseline_uris(app)

    # The conf.py entry is preserved, and each baseline URI is appended
    # anchored and escaped, so a pattern matches its URI and nothing else.
    assert app.config.linkcheck_ignore == [".*bad.*", *_ESCAPED_URIS]


@pytest.mark.parametrize("builder", [None, _FakeBuilder()], ids=["no-builder", "html"])
def test_non_linkcheck_builder_untouched(builder: object, baseline_path: Path):
    app = _app(builder=builder, baseline=str(baseline_path))

    _extension._ignore_baseline_uris(app)

    assert app.config.linkcheck_ignore == []


def test_empty_baseline_untouched():
    app = _app(builder=_linkcheck_instance(), baseline="")

    _extension._ignore_baseline_uris(app)

    assert app.config.linkcheck_ignore == []


class TestUnreadableBaseline:
    def test_missing_file(self, tmp_path: Path):
        path = str(tmp_path / "nope.json")
        app = _app(builder=_linkcheck_instance(), baseline=path)

        with pytest.raises(ExtensionError, match=re.escape(path)):
            _extension._ignore_baseline_uris(app)

    def test_directory(self, tmp_path: Path):
        # A directory path fails with IsADirectoryError, an OSError the
        # handler must catch the same way as a missing file.
        path = tmp_path / "as-a-directory"
        path.mkdir()
        app = _app(builder=_linkcheck_instance(), baseline=str(path))

        with pytest.raises(ExtensionError, match=re.escape(str(path))):
            _extension._ignore_baseline_uris(app)

    def test_invalid_json(self, tmp_path: Path):
        path = tmp_path / "baseline.json"
        path.write_text("no json here", encoding="utf-8")
        app = _app(builder=_linkcheck_instance(), baseline=str(path))

        with pytest.raises(ExtensionError, match=re.escape(str(path))):
            _extension._ignore_baseline_uris(app)


@pytest.mark.parametrize(
    "payload",
    ["[]", '"text"', "{}", '{"uris": "not a list"}'],
    ids=["list", "text", "no-uris", "uris-not-a-list"],
)
def test_not_a_baseline_raises(payload: str, tmp_path: Path):
    path = tmp_path / "baseline.json"
    path.write_text(payload, encoding="utf-8")
    app = _app(builder=_linkcheck_instance(), baseline=str(path))

    with pytest.raises(ExtensionError, match="has no uris list"):
        _extension._ignore_baseline_uris(app)


def test_register_registers():
    """``register()`` adds the config value and connects the handler."""
    connections = []
    config_values = {}

    class _Registrar:
        def add_config_value(
            self, name: str, default: object, rebuild: str, types: tuple
        ) -> None:
            config_values[name] = (default, rebuild, types)

        def connect(self, event: str, handler: object) -> None:
            connections.append((event, handler))

    _extension.register(_Registrar())  # type: ignore[arg-type]

    assert config_values["linkcheck_diff_baseline"] == ("", "linkcheck", (str,))
    assert connections == [("builder-inited", _extension._ignore_baseline_uris)]
