# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductLabelLayout(ProductCommon):
    """Cover the label layout wizard and the label report data pipeline."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product.barcode = "PROD-1"
        cls.wizard = cls.env["product.label.layout"].create(
            {"product_ids": [Command.set(cls.product.ids)]}
        )

    def _prepare_data(self, data):
        return self.env[
            "report.product.report_producttemplatelabel2x7"
        ]._get_report_values(docids=[], data=data)

    def test_dimensions_and_xml_id_per_format(self):
        expected = {
            "dymo": (1, 1, "product.report_product_template_label_dymo"),
            "2x7xprice": (2, 7, "product.report_product_template_label_2x7"),
            "4x7xprice": (4, 7, "product.report_product_template_label_4x7"),
            "4x12": (4, 12, "product.report_product_template_label_4x12_noprice"),
            "4x12xprice": (4, 12, "product.report_product_template_label_4x12"),
        }
        for print_format, (columns, rows, xml_id) in expected.items():
            with self.subTest(print_format=print_format):
                self.wizard.print_format = print_format
                self.assertEqual(self.wizard.columns, columns)
                self.assertEqual(self.wizard.rows, rows)
                got_xml_id, data = self.wizard._prepare_report_data()
                self.assertEqual(got_xml_id, xml_id)
                self.assertEqual(
                    data["price_included"], "xprice" in print_format
                )
                # The referenced report must actually exist.
                self.assertTrue(self.env.ref(xml_id))

    def test_quantity_must_be_positive(self):
        self.wizard.custom_quantity = 0
        with self.assertRaises(UserError):
            self.wizard._prepare_report_data()

    def test_no_product_raises(self):
        wizard = self.env["product.label.layout"].create({})
        with self.assertRaises(UserError):
            wizard._prepare_report_data()

    def test_page_count_boundaries(self):
        """2x7 grid = 14 labels per page: 14 labels → 1 page, 15 → 2 pages."""
        self.wizard.print_format = "2x7xprice"
        for quantity, pages in [(1, 1), (14, 1), (15, 2), (28, 2), (29, 3)]:
            with self.subTest(quantity=quantity):
                self.wizard.custom_quantity = quantity
                _xml_id, data = self.wizard._prepare_report_data()
                values = self._prepare_data(data)
                self.assertEqual(values["page_numbers"], pages)
                self.assertEqual(
                    values["quantity"][self.product],
                    [("PROD-1", quantity)],
                )

    def test_quantities_survive_json_roundtrip(self):
        """The report is called with string keys from the client flow and int
        keys when rendered server-side: both must work."""
        _xml_id, data = self.wizard._prepare_report_data()
        int_keyed = dict(data, quantity_by_product={self.product.id: 3})
        str_keyed = dict(data, quantity_by_product={str(self.product.id): 3})
        for payload in (int_keyed, str_keyed):
            values = self._prepare_data(payload)
            self.assertEqual(values["quantity"][self.product], [("PROD-1", 3)])
            self.assertEqual(values["page_numbers"], 1)

    def test_custom_barcodes_merge(self):
        """Custom barcodes add extra labels and count toward the page total."""
        self.wizard.custom_quantity = 10
        _xml_id, data = self.wizard._prepare_report_data()
        data["custom_barcodes"] = {str(self.product.id): [("LOT-1", 3), ("LOT-2", 2)]}
        values = self._prepare_data(data)
        self.assertEqual(
            values["quantity"][self.product],
            [("PROD-1", 10), ("LOT-1", 3), ("LOT-2", 2)],
        )
        # 15 labels on a 14-label grid.
        self.assertEqual(values["page_numbers"], 2)

    def test_template_path(self):
        template = self.product.product_tmpl_id
        wizard = self.env["product.label.layout"].create(
            {"product_tmpl_ids": [Command.set(template.ids)]}
        )
        _xml_id, data = wizard._prepare_report_data()
        self.assertEqual(data["active_model"], "product.template")
        values = self._prepare_data(data)
        self.assertEqual(values["quantity"][template], [("PROD-1", 1)])
