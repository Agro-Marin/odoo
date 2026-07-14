"""CI entry point for the ``project`` addon's HOOT (JS unit) suites.

The ``project`` JS test files (``static/tests/*.test.js``) were bundled into
``web.assets_unit_tests`` but no ``test_js.py`` ever selected them, so
``@project/...`` suites never ran as a gated CI check — 16 of them were
silently red when this runner was added. It mirrors
``mail/tests/test_js.py::MailSuite``: the runner machinery (hash, ``&id=``
filter, ``_run_hoot`` warm navigation) is reused from ``web`` via
``HOOTCommon``, imported through the module object so Odoo's unittest loader
does not collect ``web``'s base meta-tests a second time under ``project``.

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot --db hoot_project '@project'`` (any suite or
test path; see its README).
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# The project test tree is flat (static/tests/*.test.js), so the module root
# suite selects everything; the coverage walk below still guards against a
# future subdirectory the root hash filter would not match.
ALL_PROJECT_SUITE_PREFIXES = ("@project",)


@odoo.tests.tagged("post_install", "-at_install", "project_js")
class ProjectSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_project(self):
        """@project — all project JS unit suites (views, widgets, mocks)."""
        self._run_hoot("@project", preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least one
        method's suite prefix (see web/tests/test_js.py for the rationale:
        HOOT ``&id=`` filters fail open, so an unselected file silently never
        runs in CI)."""
        tests_root = Path(file_path("project/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@project/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_PROJECT_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Project test files selected by no CI suite filter (they will "
            "never run):\n- " + "\n- ".join(uncovered),
        )
