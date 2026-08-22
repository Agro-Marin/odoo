import logging

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

SETUP_SUFFIX = "_setup"
TEST_SUFFIX = ".test.js"


@tagged("post_install", "-at_install")
class TestSetupBundleHasNoTests(lint_case.LintCase):

    def test_setup_bundles_carry_no_test_files(self):
        offenders = []
        checked = 0
        skipped = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for bundle in self.served_bundle_names(env):
                if not bundle.endswith(SETUP_SUFFIX):
                    continue
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, js=True).files
                except Exception as exc:
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                checked += 1
                offenders.extend(
                    f"{bundle}: {url}"
                    for url in ((f["url"] or "").lstrip("/") for f in files)
                    if url.endswith(TEST_SUFFIX)
                )

        _logger.info("checked %s setup bundle(s)", checked)
        self.assertFalse(
            skipped,
            f"{len(skipped)} setup bundle(s) did not assemble, so this check "
            f"passed on silence rather than on evidence: {', '.join(skipped)}",
        )
        self.assertTrue(
            checked,
            "no *_setup bundle was checked — the naming convention this gate "
            "keys on has moved, and the gate is now vacuous",
        )
        self.assertFalse(
            offenders,
            "test file(s) in a setup bundle, which is evaluated without the "
            "per-file suite that `describe.current` needs; the page will die "
            "before HOOT starts and report no tests at all:\n  "
            + "\n  ".join(sorted(offenders)),
        )
