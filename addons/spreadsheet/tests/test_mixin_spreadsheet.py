from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMixinSpreadsheet(TransactionCase):
    def test_get_display_names_for_spreadsheet_unknown_model(self):
        display_name = self.env["mixin.spreadsheet"].get_display_names_for_spreadsheet(
            [{"model": "not.a.real.model", "id": 1}]
        )
        self.assertEqual(display_name, [None])

    def test_get_file_content_invalid_image_src_raises_validation_error(self):
        mixin = self.env["mixin.spreadsheet"]
        with self.assertRaises(ValidationError):
            mixin._get_file_content("not-a-real-path")
