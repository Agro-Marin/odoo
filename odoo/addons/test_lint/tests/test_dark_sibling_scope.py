import logging

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

DARK_SUFFIX = ".dark.scss"

DARK_MARKER = "web/static/src/scss/primitives.dark.scss"

ALLOWED = set()


@tagged("post_install", "-at_install")
class TestDarkSiblingScope(lint_case.LintCase):
    def test_dark_siblings_only_in_dark_bundles(self):
        offenders = []
        checked = 0
        empty = []
        skipped = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for bundle in self.served_bundle_names(env):
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, css=True).files
                except Exception as exc:
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                if not files:
                    empty.append(bundle)
                    continue
                checked += 1
                urls = [(f["url"] or "").lstrip("/") for f in files]
                if DARK_MARKER in urls:
                    continue
                offenders.extend(
                    f"{bundle}: {url}"
                    for url in urls
                    if url.endswith(DARK_SUFFIX) and (bundle, url) not in ALLOWED
                )

        _logger.info("checked %s bundles with files", checked)
        self.assertFalse(
            skipped,
            f"{len(skipped)} served bundle(s) did not assemble, so this check "
            f"never looked at them; `TestBundlesAssemble` owns that:\n  "
            + "\n  ".join(skipped),
        )
        self.assertFalse(
            empty,
            f"{len(empty)} served bundle(s) assembled to no files:\n  "
            + "\n  ".join(empty),
        )
        self.assertFalse(
            offenders,
            f"{len(offenders)} dark sibling(s) in a bundle that never compiled "
            f"the dark palette. Exclude them with a `remove` directive, and "
            f"name them back in the matching dark bundle if they belong to "
            f"one:\n  " + "\n  ".join(offenders),
        )
