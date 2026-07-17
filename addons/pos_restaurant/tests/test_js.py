"""CI entry point for the ``pos_restaurant`` addon's HOOT (JS unit) suite.

Mirrors ``point_of_sale/tests/test_js.py``: the runner machinery (hash, ``&id=``
filter, ``_run_hoot`` warm navigation) is reused from ``web`` via ``HOOTCommon``,
imported through the module object so Odoo's unittest loader does not collect
``web``'s base meta-tests a second time under ``pos_restaurant``.

Only ``static/tests/unit`` is bundled into ``web.assets_unit_tests``; the
coverage walk fails if any bundled ``*.test.js`` is selected by no suite prefix
(HOOT ``&id=`` filters fail open, so an unselected file silently never runs).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

ALL_SUITE_PREFIXES = ("@pos_restaurant/unit",)


@odoo.tests.tagged("post_install", "-at_install", "pos_restaurant_js")
class PosRestaurantSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_pos_restaurant_unit(self):
        """@pos_restaurant/unit — the pos_restaurant JS unit suites (models,
        components, services)."""
        self._run_hoot("@pos_restaurant/unit", preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        tests_root = Path(file_path("pos_restaurant/static/tests"))
        uncovered = []
        for test_file in sorted((tests_root / "unit").rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@pos_restaurant/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "pos_restaurant unit test files selected by no CI suite filter (they "
            "will never run):\n- " + "\n- ".join(uncovered),
        )
