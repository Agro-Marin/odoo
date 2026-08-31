from odoo.tests.common import TransactionCase


class TestMixinSpreadsheet(TransactionCase):
    def test_get_display_names_for_spreadsheet_unknown_model(self):
        display_name = self.env["mixin.spreadsheet"].get_display_names_for_spreadsheet(
            [{"model": "not.a.real.model", "id": 1}]
        )
        self.assertEqual(display_name, [None])
