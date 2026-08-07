import logging

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestBundlesAssemble(lint_case.LintCase):
    def test_every_declared_bundle_assembles(self):
        failures = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            bundles = self.served_bundle_names(env)

            self.assertTrue(bundles, "no bundles found — the scan reached nothing")

            ir_asset = env["ir.asset"]
            params = ir_asset._get_asset_params()
            for bundle in bundles:
                try:
                    ir_asset._get_asset_paths(bundle, params)
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")

        self.assertFalse(
            failures,
            f"{len(failures)} of {len(bundles)} declared bundle(s) do not "
            "assemble:\n" + "\n".join(failures),
        )
        _logger.info("%s served bundles assemble", len(bundles))
