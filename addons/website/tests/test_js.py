# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""CI entry point for the ``website`` addon's HOOT (JS unit) suites.

The ``website`` JS test files (``static/tests/**/*.test.js`` -- 121 files
covering the page builder, the public-side interactions and the core services)
were bundled into ``web.assets_unit_tests`` but **no** ``test_js.py`` ever
selected them, so ``@website/...`` suites never ran as a gated CI check. That is
the same gap ``mail`` and ``bus`` closed; this class wires ``website`` in the
same way.

The tree is fanned out across several ``test_*`` methods so a single failing
area is isolated and the run can be sharded, and a coverage walk fails the build
the moment a new ``static/tests`` directory is added without being selected by a
method.

The runner machinery (hash, ``&id=`` filter, ``_run_hoot`` warm navigation) is
reused from ``web`` via ``HOOTCommon``, imported through the module object
(``web_test_js.HOOTCommon``) rather than a bare ``from ... import`` so Odoo's
unittest loader does not collect ``web``'s base meta-tests a second time under
``website``.

Note ``static/tests/tours`` holds tour definitions, not HOOT suites: they ship
in ``web.assets_tests`` and are driven from the Python ``HttpCase`` tours, so
they are deliberately outside this file's remit (and contain no ``*.test.js``).

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot --db <db> '@website/builder'`` (any suite
path; see its README).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# The builder tree is by far the largest (68 files), so it is split by
# second-level directory to keep each method a bounded run.
BUILDER_SUITES = (
    "@website/builder/custom_tab",
    "@website/builder/options",
    "@website/builder/theme_tab",
    "@website/builder/website_builder",
)
MISC_SUITES = (
    "@website/core",
    # root-level test files (website/static/tests/*.test.js)
    "@website/new_content_systray_item",
    "@website/page_url_field",
    "@website/redirect_field",
)
# Union of every prefix some method selects -- kept in sync with the methods
# below and checked exhaustively by test_suite_filters_cover_every_test_file.
ALL_WEBSITE_SUITE_PREFIXES = (
    "@website/builder",
    "@website/interactions",
    *BUILDER_SUITES,
    *MISC_SUITES,
)


@odoo.tests.tagged("post_install", "-at_install", "website_js")
class WebsiteSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_builder(self):
        """@website/builder -- page builder: save, drag & drop, overlays."""
        self._run_hoot("@website/builder", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_interactions(self):
        """@website/interactions -- public-side snippet interactions."""
        self._run_hoot("@website/interactions", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_misc(self):
        """@website/core plus the root-level backend field tests."""
        self._run_hoot(*MISC_SUITES, preset="desktop")

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least one
        method's suite prefix. HOOT ``&id=`` hash filters resolve against suite
        names, so a tests directory no method names simply never runs -- which
        is precisely how all 121 of these files came to be dead. This walk fails
        the build the moment one is added or renamed without updating the suite
        lists at the top of this file."""
        tests_root = Path(file_path("website/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@website/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_WEBSITE_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Website test files selected by no CI suite filter (they will never "
            "run):\n- " + "\n- ".join(uncovered),
        )
