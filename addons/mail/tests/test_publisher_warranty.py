from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools import cloc


class TestPublisherWarrantyMaintenance(TransactionCase):
    def test_message_includes_maintenance_payload(self):
        message = self.env["publisher_warranty.contract"]._get_message()
        self.assertIn("maintenance", message)
        self.assertEqual(message["maintenance"]["version"], cloc.VERSION)
        stored = self.env["ir.config_parameter"].get_param("publisher_warranty.cloc")
        self.assertTrue(stored)
        self.assertIn("version", stored)

    def test_message_maintenance_disabled(self):
        self.env["ir.config_parameter"].set_param(
            "publisher_warranty.maintenance_disable", "1"
        )
        message = self.env["publisher_warranty.contract"]._get_message()
        self.assertNotIn("maintenance", message)

    def test_message_maintenance_falsy_string_not_disabled(self):
        self.env["ir.config_parameter"].set_param(
            "publisher_warranty.maintenance_disable", "0"
        )
        message = self.env["publisher_warranty.contract"]._get_message()
        self.assertIn("maintenance", message)

    def test_cloc_failure_is_logged(self):
        with patch("odoo.tools.cloc.Cloc.count_env", side_effect=RuntimeError("boom")):
            with self.assertLogs("odoo.addons.mail.models.update", level="ERROR"):
                message = self.env["publisher_warranty.contract"]._get_message()
        self.assertEqual(message["maintenance"]["errors"], ["cloc/error"])

    def test_verbose_maintenance_debug_payload(self):
        result = self.env["publisher_warranty.contract"]._get_verbose_maintenance()
        self.assertIn("modules_count", result)
        self.assertIn("modules_excluded", result)
