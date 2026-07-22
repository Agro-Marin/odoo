"""CI entry point for the ``website`` addon's HOOT (JS unit) suites.

The ``website`` JS test files (``static/tests/**/*.test.js`` -- 121 of them at
the time of writing) are bundled into ``web.assets_unit_tests``, but no
``test_js.py`` ever selected them, so ``@website/...`` suites never ran as a
gated CI check. Nothing failed loudly; they were simply never executed, and
several whole trees had rotted (the builder tree could not even load its
``website.website_builder_assets`` bundle). This class wires them in, mirroring
``bus/tests/test_js.py::BusSuite``.

The runner machinery (hash, ``&id=`` filter, ``_run_hoot`` warm navigation) is
reused verbatim from ``web`` via the ``HOOTCommon`` base. It is imported through
the module object (``web_test_js.HOOTCommon``) rather than ``from ... import
HOOTCommon`` on purpose: binding the name into this module's namespace would
make Odoo's unittest loader collect ``web``'s base meta-tests a second time
under ``website``.

Unlike ``bus``, the suites are split per top-level tests directory rather than
run under one ``@website`` filter: the builder tree alone is several hundred
DOM-heavy tests and a single navigation for the whole module runs long enough
to hit the browser timeout. Splitting also keeps a failure's blast radius to
one method. Because that turns the selection into a hand-maintained list,
``test_suite_filters_cover_every_test_file`` guards it -- HOOT ``&id=`` filters
fail open, so a tests directory nobody names silently never runs (exactly the
hole this file closes).

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot '@website/builder'`` (any suite or test path;
see its README).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# Every ``static/tests`` entry maps to exactly one suite prefix below. Keep in
# sync when adding a tests directory -- ``test_suite_filters_cover_every_test_
# file`` fails the build otherwise.
ALL_WEBSITE_SUITE_PREFIXES = (
    "@website/builder",
    "@website/core",
    "@website/interactions",
    "@website/new_content_systray_item",
    "@website/page_url_field",
    "@website/redirect_field",
)


@odoo.tests.tagged("post_install", "-at_install", "website_js")
class WebsiteSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_builder(self):
        """@website/builder — website builder/editor OWL suites."""
        self._run_hoot("@website/builder", preset="desktop", timeout=1800)

    @odoo.tests.no_retry
    def test_interactions(self):
        """@website/interactions — public-site Interactions (+ .edit variants)."""
        self._run_hoot("@website/interactions", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_misc(self):
        """@website/core plus the root-level field/systray suites."""
        self._run_hoot(
            "@website/core",
            "@website/new_content_systray_item",
            "@website/page_url_field",
            "@website/redirect_field",
            preset="desktop",
        )

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least one
        method's suite prefix (see web/tests/test_js.py for the rationale:
        HOOT ``&id=`` filters fail open, so an unselected file silently never
        runs in CI)."""
        tests_root = Path(file_path("website/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            if rel.startswith("tours/"):
                # Tours run through web.assets_tests and the Python
                # `start_tour` suites, not the HOOT unit runner.
                continue
            suite = "@website/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_WEBSITE_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Website test files selected by no CI suite filter (they will "
            "never run):\n- " + "\n- ".join(uncovered),
        )
