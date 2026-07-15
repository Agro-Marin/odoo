"""CI entry point for the ``point_of_sale`` addon's HOOT (JS unit) suites.

The ``point_of_sale`` JS unit test files (``static/tests/unit/**/*.test.js``) are
bundled into ``web.assets_unit_tests`` (see ``__manifest__.py``) but no
``test_js.py`` ever selected them, so the ``@point_of_sale/unit`` suites never ran
as a gated CI check — the whole suite was silently broken (it could not even
start) when this runner was added. It mirrors
``project/tests/test_js.py::ProjectSuite``: the runner machinery (hash, ``&id=``
filter, ``_run_hoot`` warm navigation) is reused from ``web`` via ``HOOTCommon``,
imported through the module object so Odoo's unittest loader does not collect
``web``'s base meta-tests a second time under ``point_of_sale``.

Only ``static/tests/unit`` is bundled into ``web.assets_unit_tests``; other trees
(``pos/tours``, ``generic_helpers``, ``customer_display`` helpers, the unbundled
``generic_components``) are not HOOT unit suites and are intentionally not
selected here — the coverage walk below therefore scopes itself to ``unit``.

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot --db hoot_pos '@point_of_sale/unit'`` (any suite
or test path; see its README).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# The bundled point_of_sale unit tree lives under `unit/`; the module-root unit
# suite selects everything below it. The coverage walk guards against a future
# unit test file that the root hash filter would not match.
ALL_POS_SUITE_PREFIXES = ("@point_of_sale/unit",)


@odoo.tests.tagged("post_install", "-at_install", "point_of_sale_js")
class PointOfSaleSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_point_of_sale_unit(self):
        """@point_of_sale/unit — models, components, services, related_models,
        accounting, customer_display and tools JS unit suites."""
        self._run_hoot("@point_of_sale/unit", preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        """Every bundled ``static/tests/unit/**/*.test.js`` must be selected by at
        least one method's suite prefix (see web/tests/test_js.py for the
        rationale: HOOT ``&id=`` filters fail open, so an unselected file silently
        never runs in CI)."""
        tests_root = Path(file_path("point_of_sale/static/tests"))
        uncovered = []
        for test_file in sorted((tests_root / "unit").rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@point_of_sale/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_POS_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "point_of_sale unit test files selected by no CI suite filter (they "
            "will never run):\n- " + "\n- ".join(uncovered),
        )
