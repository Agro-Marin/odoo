from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

ALL_WEBSITE_SUITE_PREFIXES = (
    "@website/builder",
    "@website/core",
    "@website/interactions",
    "@website/new_content_systray_item",
    "@website/page_dependencies",
    "@website/page_url_field",
    "@website/redirect_field",
)


@odoo.tests.tagged("post_install", "-at_install", "website_js")
class WebsiteSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_builder(self):
        self._run_hoot("@website/builder", preset="desktop", timeout=1800)

    @odoo.tests.no_retry
    def test_interactions(self):
        self._run_hoot("@website/interactions", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_misc(self):
        self._run_hoot(
            "@website/core",
            "@website/new_content_systray_item",
            "@website/page_dependencies",
            "@website/page_url_field",
            "@website/redirect_field",
            preset="desktop",
        )

    def test_suite_filters_cover_every_test_file(self):
        tests_root = Path(file_path("website/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            if rel.startswith("tours/"):
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
