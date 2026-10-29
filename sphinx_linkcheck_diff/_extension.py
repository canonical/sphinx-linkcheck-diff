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

"""The baseline filter: ignore URIs the base branch's baseline lists.

With ``linkcheck_diff_baseline`` set to a baseline JSON path, a
linkcheck build reports only URIs that are new or changed relative
to the base branch. Sphinx loads the extension through the package's
``setup()``.
"""

import json
import re
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.builders.linkcheck import CheckExternalLinksBuilder
from sphinx.errors import ExtensionError


def _ignore_baseline_uris(app: Sphinx) -> None:
    """Add each baseline URI to ``linkcheck_ignore``.

    The builder type is checked first, so ``make html`` and any other
    build is unaffected. An empty ``linkcheck_diff_baseline`` means
    dormancy: nothing is read and nothing changes.
    """
    builder = app.builder
    if not isinstance(builder, CheckExternalLinksBuilder):
        return
    baseline_path = app.config.linkcheck_diff_baseline
    if not baseline_path:
        return
    # str() first: a wrong-typed value from conf.py would otherwise
    # crash Path() with a TypeError before the error can name the value.
    try:
        baseline: dict[str, Any] = json.loads(
            Path(str(baseline_path)).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtensionError(
            f"linkcheck-diff: can't read baseline {baseline_path}: {exc}"
        ) from exc
    # A corrupt baseline can hold other JSON (a list, a string), so the
    # shape is checked at runtime, not by the annotation.
    if not isinstance(baseline, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ExtensionError(
            f"linkcheck-diff: baseline {baseline_path} has no uris list"
        )
    if not isinstance(baseline.get("uris"), list):
        raise ExtensionError(
            f"linkcheck-diff: baseline {baseline_path} has no uris list"
        )
    uris: list[str] = []
    for uri in baseline["uris"]:
        # A baseline the collector writes holds only strings. A
        # non-string entry means a hand edit, and hand edits fail the
        # build.
        if not isinstance(uri, str):
            raise ExtensionError(
                f"linkcheck-diff: baseline {baseline_path} has a uri "
                f"that is not a string: {uri!r}"
            )
        uris.append(uri)
    # Anchored and escaped, so a baseline URI matches itself and nothing
    # else. ``linkcheck_ignore`` may arrive as a tuple, so a new list is
    # assigned, existing entries first.
    app.config.linkcheck_ignore = [
        *app.config.linkcheck_ignore,
        *(f"^{re.escape(uri)}$" for uri in uris),
    ]


def register(app: Sphinx) -> None:
    """Register the config value and the ``builder-inited`` handler."""
    app.add_config_value(
        name="linkcheck_diff_baseline",
        default="",
        # Sphinx accepts any rebuild string at runtime, but its
        # _ConfigRebuild typing doesn't list 'linkcheck'.
        rebuild="linkcheck",  # type: ignore[arg-type]
        types=(str,),
    )
    # Sphinx 7.4 types the callback parameter as a bare ``Callable``,
    # which pyright strict rejects.
    app.connect(  # pyright: ignore[reportUnknownMemberType]
        "builder-inited",
        _ignore_baseline_uris,
    )
