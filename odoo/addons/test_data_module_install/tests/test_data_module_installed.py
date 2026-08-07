from odoo.tests import common


class TestDataModuleInstalled(common.TransactionCase):
    def test_data_module_installed(self):

        data_module = self.env["ir.module.module"].search(
            [("name", "=", "test_data_module")]
        )
        self.assertEqual(data_module.state, "installed")
