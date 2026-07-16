"""CI entry point for the ``test_mail`` addon's HOOT (JS unit) suites.

``test_mail`` bundles its JS tests into ``web.assets_unit_tests``
(``__manifest__.py``) but no ``test_js.py`` ever selected them, so these
suites never ran as a gated CI check — including the only tests of the
**activity view** (controller/renderer/compiler), chatter-on-test-models,
tracking values and the activity systray. This class wires them in,
mirroring ``mail/tests/test_js.py``: the runner machinery is reused from
``web`` via ``HOOTCommon`` (imported through the module object so Odoo's
unittest loader does not collect ``web``'s base meta-tests a second time),
and a coverage walk fails the build the moment a new ``static/tests`` file
is added without being selected by a method.

Only the **desktop** preset is wired (mobile-tagged tests such as
``activity_mobile`` are selected but skipped by the preset), consistent
with ``mail``'s suite; a mobile pass can be added once validated there.

Fast local runs use the warm-server runner instead:
``addons/web/tooling/scripts/hoot --db hoot_test_mail '@test_mail/activity'``.
"""

from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

import odoo.addons.web.tests.test_js as web_test_js

ACTIVITY_SUITES = (
    "@test_mail/activity",
    "@test_mail/activity_mobile",
    "@test_mail/systray_activity_menu",
)
MISC_SUITES = (
    "@test_mail/attachment_view",
    "@test_mail/chatter",
    "@test_mail/properties_field",
    "@test_mail/tracking_value",
)
# Union of every prefix some method selects — checked exhaustively by
# test_suite_filters_cover_every_test_file.
ALL_TEST_MAIL_SUITE_PREFIXES = (*ACTIVITY_SUITES, *MISC_SUITES)


@odoo.tests.tagged("post_install", "-at_install", "test_mail_js")
class TestMailSuite(web_test_js.HOOTCommon):
    @odoo.tests.no_retry
    def test_activity(self):
        """@test_mail/activity* — activity view, mobile layout, systray."""
        self._run_hoot(*ACTIVITY_SUITES, preset="desktop")

    @odoo.tests.no_retry
    def test_misc(self):
        """Chatter on test models, attachment view, properties, tracking."""
        self._run_hoot(*MISC_SUITES, preset="desktop")

    def test_suite_filters_cover_every_test_file(self):
        """Every ``static/tests/**/*.test.js`` must be selected by at least
        one method's suite prefix — HOOT ``&id=`` filters resolve against
        suite names, so a test file no method names simply never runs (the
        exact failure mode this file exists to fix)."""
        tests_root = Path(file_path("test_mail/static/tests"))
        uncovered = []
        for test_file in sorted(tests_root.rglob("*.test.js")):
            rel = test_file.relative_to(tests_root).as_posix()
            suite = "@test_mail/" + rel[: -len(".test.js")]
            if not any(
                suite == prefix or suite.startswith(prefix + "/")
                for prefix in ALL_TEST_MAIL_SUITE_PREFIXES
            ):
                uncovered.append(suite)
        self.assertFalse(
            uncovered,
            "test_mail test files selected by no CI suite filter (they will "
            "never run):\n- " + "\n- ".join(uncovered),
        )
