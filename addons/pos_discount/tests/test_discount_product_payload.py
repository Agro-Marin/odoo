from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestPosDiscountProductPayload(CommonPosTest):
    """The discount product reaches the terminal through pos.config's special
    products, not through a second lookup keyed on the wrong model's id."""

    def setUp(self):
        super().setUp()
        self.config = self.pos_config_usd
        self.discount_product = self.env["product.product"].create(
            {
                "name": "Global discount probe",
                "type": "service",
                "list_price": 0.0,
                "available_in_pos": False,
                "taxes_id": False,
            }
        )
        self.config.write(
            {
                "module_pos_discount": True,
                "discount_product_id": self.discount_product.id,
            }
        )
        self.config.open_ui()

    def _rows(self):
        data = {"pos.config": [{"_pos_special_products_ids": []}]}
        return self.env["product.template"]._load_pos_data_search_read(
            data, self.config
        )

    def test_the_discount_product_is_loaded_once(self):
        template_id = self.discount_product.product_tmpl_id.id
        self.assertEqual(
            [row["id"] for row in self._rows()].count(template_id),
            1,
            "the special-product union already carries it; a second append would "
            "duplicate it",
        )

    def test_the_discount_product_row_is_post_processed(self):
        template_id = self.discount_product.product_tmpl_id.id
        row = next(row for row in self._rows() if row["id"] == template_id)
        self.assertIsInstance(row["image_128"], bool)
        self.assertIn("_archived_combinations", row)
