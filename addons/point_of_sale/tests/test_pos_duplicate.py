from odoo.tests.common import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosDuplicate(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.category = self.env["pos.category"].create({"name": "Drinks"})
        self.preset = self.env["pos.preset"].create({"name": "Take away"})
        self.printer = self.env["pos.printer"].create(
            {
                "name": "Kitchen",
                "proxy_ip": "10.0.0.1",
                "pos_config_ids": [(6, 0, self.basic_config.ids)],
            }
        )

    def test_duplicate_marks_the_copy_in_its_name(self):
        self.assertEqual(
            self.basic_config.copy().name, f"{self.basic_config.name} (copy)"
        )
        self.assertEqual(self.category.copy().name, "Drinks (copy)")
        self.assertEqual(self.preset.copy().name, "Take away (copy)")
        self.assertEqual(self.printer.copy().name, "Kitchen (copy)")
        self.assertEqual(self.bank_pm1.copy().name, f"{self.bank_pm1.name} (copy)")

    def test_duplicate_a_note_no_longer_breaks_its_unique_name(self):
        note = self.env["pos.note"].create({"name": "No onions"})
        self.assertEqual(note.copy().name, "No onions (copy)")

    def test_an_explicit_name_wins_over_the_copy_marker(self):
        self.assertEqual(self.category.copy({"name": "Sodas"}).name, "Sodas")
        self.assertEqual(
            self.basic_config.copy({"name": "Second shop"}).name, "Second shop"
        )

    def test_a_duplicated_printer_starts_detached_from_every_point_of_sale(self):
        copied = self.printer.copy()
        self.assertFalse(copied.pos_config_ids)
        self.assertEqual(copied.epson_printer_ip, "0.0.0.0")
