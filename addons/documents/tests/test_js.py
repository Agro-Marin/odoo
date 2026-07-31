"""CI entry point for the ``documents`` addon's HOOT (JS unit) suites.

The 26 ``static/tests/**/*.test.js`` files were bundled into
``web.assets_unit_tests`` but **no** ``test_js.py`` ever selected them, so
``@documents/...`` suites never ran as a gated check -- neither before nor after
the module was split into ``documents`` / ``documents_enterprise``. This class
wires them in, mirroring ``mail/tests/test_js.py::MailSuite``: the tree is fanned
out across a few ``test_*`` methods so a failing area is isolated and the run can
be sharded, and a coverage walk fails the build the moment a test file is added
or renamed without being selected.

The runner machinery (hash, ``&id=`` filter, ``_run_hoot`` warm navigation) is
reused from ``web`` via ``HOOTCommon``, imported through the module object
(``web_test_js.HOOTCommon``) rather than a bare ``from ... import`` so Odoo's
unittest loader does not collect ``web``'s base meta-tests a second time here.

Fast local runs use the warm-server runner instead:
``tooling/hoot/hoot --db <db> '@documents/kanban_view'``.
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

# Grouped so each method is a bounded run. Every test file MUST be selected by
# exactly one group (test_suite_filters_cover_every_test_file enforces it).
VIEW_SUITES = (
    "@documents/views",  # views/fields/*.test.js
    "@documents/kanban_view",
    "@documents/list_view",
    "@documents/multi_view",
    "@documents/search_model",
    "@documents/search_panel",
    "@documents/select_all",
    "@documents/draggable_drop_rules",
)
PDF_SUITES = (
    "@documents/pdf_manager",
    "@documents/pdf_page_store",
)
MISC_SUITES = (
    "@documents/activity_menu_patch",
    "@documents/chatter_visible_storage",
    "@documents/details_panel",
    "@documents/documents_systray_activity_menu",
    "@documents/document_to_restore",
    "@documents/error_dialog_patch",
    "@documents/log_access",
    "@documents/manage_versions",
    "@documents/model_mixin",
    "@documents/notifications_systray",
    "@documents/operation",
    "@documents/preview_lifecycle",
    "@documents/thumbnail_service",
)
# Union of every prefix some method selects, checked by the coverage walk.
ALL_DOCUMENTS_SUITE_PREFIXES = (*VIEW_SUITES, *PDF_SUITES, *MISC_SUITES)

# Every JS test in this addon passes. The tuple is kept (rather than deleted
# along with `_excluding_known_failures`) so that quarantining a test is a
# one-line change with a visible name, instead of a temptation to drop a whole
# suite from the lists above -- which is how this tree came to have 26 test
# files that no CI job selected.
KNOWN_FAILURES = ()


@odoo.tests.tagged("post_install", "-at_install", "documents_js")
class DocumentsSuite(web_test_js.HOOTCommon):
    def _excluding_known_failures(self, *prefixes):
        """Return the ``&id=-<hash>`` filters for KNOWN_FAILURES under *prefixes*."""
        return "".join(
            f"&id=-{self._generate_hash(name)}"
            for name in KNOWN_FAILURES
            if any(name.startswith(prefix + "/") for prefix in prefixes)
        )

    @odoo.tests.no_retry
    def test_views(self):
        """Kanban / list / multi-view, the search model and the field widgets."""
        self._run_hoot(
            *VIEW_SUITES,
            preset="desktop",
            timeout=900,
            extra=self._excluding_known_failures(*VIEW_SUITES),
        )

    @odoo.tests.no_retry
    def test_pdf(self):
        """The PDF split manager and its page store."""
        self._run_hoot(*PDF_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_misc(self):
        """Details panel, previews, thumbnails, activity/systray patches, …"""
        self._run_hoot(
            *MISC_SUITES,
            preset="desktop",
            timeout=900,
            extra=self._excluding_known_failures(*MISC_SUITES),
        )

    def test_known_failures_are_still_named_correctly(self):
        """A KNOWN_FAILURES entry must name a real test file's suite.

        A typo would silently exclude nothing (and the suite would go red) or,
        worse, match nothing while looking like it covers something. Check the
        suite part against the files on disk.
        """
        tests_root = Path(file_path("documents/static/tests"))
        suites = {
            "@documents/" + p.relative_to(tests_root).as_posix()[: -len(".test.js")]
            for p in tests_root.rglob("*.test.js")
        }
        for name in KNOWN_FAILURES:
            self.assertTrue(
                any(name.startswith(suite + "/") for suite in suites),
                f"KNOWN_FAILURES entry names no existing test file: {name}",
            )

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by some method.

        HOOT ``&id=`` hash filters resolve against suite names, so a file no
        method names simply never runs -- silently, with the suite still green.
        This walk fails the moment one is added or renamed without updating the
        lists above.
        """
        tests_root = Path(file_path("documents/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@documents/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_DOCUMENTS_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "Documents test files selected by no CI suite filter (they will "
            "never run):\n- " + "\n- ".join(uncovered),
        )
