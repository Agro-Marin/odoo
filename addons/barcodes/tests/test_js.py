"""CI entry point for the ``barcodes`` addon's HOOT (JS unit) suite.

The addon bundles ``static/tests/*.test.js`` into ``web.assets_unit_tests``
but declared no runner, so nothing selected those suites: ``_run_hoot`` drives
HOOT with ``&id=`` filters built from explicit suite names, and a file no filter
names simply never runs.

Mirrors ``pos_loyalty/tests/test_js.py``: the runner machinery (hash, ``&id=``
filter, ``_run_hoot`` warm navigation) is reused from ``web`` via ``HOOTCommon``,
imported through the module object so Odoo's unittest loader does not collect
``web``'s base meta-tests a second time under ``barcodes``.
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

ALL_SUITE_PREFIXES = ("@barcodes",)


@odoo.tests.tagged("post_install", "-at_install", "barcodes_js")
class BarcodesSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_barcodes_unit(self):
        """@barcodes — the barcode parser, scanner and field JS suites."""
        self._run_hoot("@barcodes", preset="desktop", timeout=900)

    @odoo.tests.no_retry
    def test_barcodes_unit_mobile(self):
        """@barcodes under the mobile preset.

        ``barcode_mobile`` patches the barcode service's ``isMobileChrome`` and
        drives touch-keyboard behaviour, so it registers nothing under the
        desktop preset and the desktop run above never reaches it.
        """
        self._run_hoot("@barcodes", preset="mobile", tag="-headless", timeout=900)

    def test_suite_filters_cover_every_test_file(self):
        tests_root = Path(file_path("barcodes/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@barcodes/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "barcodes unit test files selected by no CI suite filter (they "
            "will never run):\n- " + "\n- ".join(uncovered),
        )
