"""CI entry point for the ``base_import`` addon's HOOT (JS unit) suite.

The addon bundles ``static/tests/**/*.test.js`` into ``web.assets_unit_tests``
but declared no runner, so nothing ever executed those suites: ``web``'s own
``WebSuite`` only selects ``@web/...`` prefixes, and its coverage walk only
inspects ``web``'s own test files. The import action and import records suites
were therefore dead weight in the bundle.

Mirrors ``pos_loyalty/tests/test_js.py``: the runner machinery (hash, ``&id=``
filter, ``_run_hoot`` warm navigation) is reused from ``web`` via ``HOOTCommon``,
imported through the module object so Odoo's unittest loader does not collect
``web``'s base meta-tests a second time under ``base_import``.
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

ALL_SUITE_PREFIXES = ("@base_import",)


@odoo.tests.tagged("post_install", "-at_install", "base_import_js")
class BaseImportSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_base_import_unit(self):
        """@base_import — the import action and import records JS suites."""
        self._run_hoot("@base_import", preset="desktop", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        tests_root = Path(file_path("base_import/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@base_import/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "base_import unit test files selected by no CI suite filter (they "
            "will never run):\n- " + "\n- ".join(uncovered),
        )
