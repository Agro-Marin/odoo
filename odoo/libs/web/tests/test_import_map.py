"""Tests for ``odoo.libs.web.import_map`` and the pages that hand-roll a map."""

import base64
import hashlib
import json
import re
import unittest
from pathlib import Path

from odoo.libs.constants import ODOO_EXTERNAL_LIBS
from odoo.libs.web.import_map import import_map_for

_TAG_BODY = re.compile(r'<script type="importmap">(?P<body>.*?)</script>', re.DOTALL)

_REPO_ROOT = Path(__file__).resolve().parents[4]

_OVERRIDE_DIRS = (_REPO_ROOT / "addons/web/static/lib/hoot/tests",)


def _sha256_expr(body: str) -> str:
    return (
        f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
    )


class TestImportMapFor(unittest.TestCase):
    def test_resolves_urls_from_the_external_libs_registry(self):
        map_ = import_map_for("@popperjs/core")
        self.assertEqual(
            json.loads(_TAG_BODY.search(map_.script_tag)["body"]),
            {"imports": {"@popperjs/core": ODOO_EXTERNAL_LIBS["@popperjs/core"]}},
        )

    def test_hash_covers_exactly_the_emitted_inline_body(self):
        """The invariant the whole helper exists for: a browser hashes the text
        between the tags, so that text and ``csp_hash`` must never disagree."""
        for specs in (("@popperjs/core",), ("luxon", "dompurify"), ("@odoo/owl",)):
            with self.subTest(specs=specs):
                map_ = import_map_for(*specs)
                body = _TAG_BODY.search(map_.script_tag)["body"]
                self.assertEqual(map_.csp_hash, _sha256_expr(body))

    def test_hash_matches_a_browser_computed_value(self):
        """Known answer: Chrome asked for this exact expression when refusing
        the IoT homepage's inline map."""
        body = '{"imports": {"@popperjs/core": "/web/static/lib/popper/popper.esm.js"}}'
        self.assertEqual(
            _sha256_expr(body),
            "'sha256-L6D+Pkeols3LJsHdaiuYaUiHBEoDxCFlqxK/S6jJ96I='",
        )

    def test_output_is_deterministic_and_order_independent(self):
        self.assertEqual(
            import_map_for("luxon", "@popperjs/core"),
            import_map_for("@popperjs/core", "luxon"),
        )

    def test_unregistered_specifier_is_rejected(self):
        with self.assertRaises(KeyError) as caught:
            import_map_for("@popperjs/core", "left-pad")
        self.assertIn("left-pad", str(caught.exception))


class TestHardcodedImportMaps(unittest.TestCase):
    """Pages outside the asset pipeline may still inline their own map.

    Where they do, the URLs must agree with ``ODOO_EXTERNAL_LIBS`` — otherwise a
    vendored library moves and those pages keep pointing at the old path.
    """

    def _hardcoded_maps(self):
        for pattern in ("addons/**/*.html", "addons/**/*.xml"):
            for path in _REPO_ROOT.glob(pattern):
                if any(path.is_relative_to(d) for d in _OVERRIDE_DIRS):
                    continue
                try:
                    source = path.read_text(encoding="utf-8")
                except OSError, UnicodeDecodeError:
                    continue
                if 'type="importmap"' not in source:
                    continue
                for match in _TAG_BODY.finditer(source):
                    try:
                        imports = json.loads(match["body"]).get("imports", {})
                    except json.JSONDecodeError:
                        continue
                    yield path, imports

    def test_hardcoded_maps_agree_with_the_registry(self):
        checked = 0
        for path, imports in self._hardcoded_maps():
            for spec, url in imports.items():
                if spec not in ODOO_EXTERNAL_LIBS:
                    continue
                checked += 1
                self.assertEqual(
                    url,
                    ODOO_EXTERNAL_LIBS[spec],
                    f"{path.relative_to(_REPO_ROOT)} pins a stale URL for {spec!r}; "
                    f"prefer odoo.libs.web.import_map.import_map_for()",
                )
        self.assertGreater(
            checked, 0, "import-map scan matched nothing — check the glob"
        )
