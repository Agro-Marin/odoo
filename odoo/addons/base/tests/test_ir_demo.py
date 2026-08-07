from unittest.mock import patch

from odoo.exceptions import AccessDenied
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestIrDemo(TransactionCase):
    def test_install_demo_denies_non_admin(self):
        user = new_test_user(self.env, login="demo_gate_user")
        demo = self.env["ir.demo"].with_user(user)
        with (
            patch("odoo.modules.loading.force_demo") as force_demo,
            mute_logger("odoo.addons.base.models.ir_module"),
        ):
            with self.assertRaises(AccessDenied):
                demo.install_demo()
            force_demo.assert_not_called()

    def test_install_demo_admin_gated_path(self):
        with patch("odoo.modules.loading.force_demo") as force_demo:
            action = self.env["ir.demo"].install_demo()
            force_demo.assert_called_once()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["url"], "/odoo")
        self.assertEqual(action["target"], "self")


@tagged("post_install", "-at_install")
class TestIrDemoFailure(TransactionCase):
    def test_error_field_stores_multiline_traceback(self):
        module = self.env["ir.module.module"].search([], limit=1)
        multiline = "Traceback (most recent call last):\n  File ...\nValueError: boom"
        failure = self.env["ir.demo_failure"].create(
            {"module_id": module.id, "error": multiline}
        )
        self.assertEqual(failure.error, multiline)
        self.assertEqual(failure._fields["error"].type, "text")

    def test_wizard_aggregates_orphan_failures(self):
        modules = self.env["ir.module.module"].search([], limit=3)
        self.assertTrue(modules, "Expected at least one installed module to reference")
        Failure = self.env["ir.demo_failure"]
        failures = Failure.browse()
        for module in modules:
            failures |= Failure.create({"module_id": module.id, "error": "boom"})

        orphans = Failure.search([("wizard_id", "=", False)])
        self.assertTrue(
            failures <= orphans, "Newly created failures must be orphan rows"
        )
        wizard = self.env["ir.demo_failure.wizard"].create(
            {"failure_ids": [(6, 0, orphans.ids)]}
        )

        self.assertEqual(wizard.failures_count, len(orphans))
        self.assertEqual(wizard.failure_ids, orphans)
        self.assertTrue(failures <= wizard.failure_ids)
