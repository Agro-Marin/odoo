from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductPackagingBarcodes(ProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.box = cls.env["uom.uom"].create(
            {
                "name": "Box of 12",
                "relative_factor": 12,
                "relative_uom_id": cls.uom_unit.id,
            }
        )
        cls.template = cls.env["product.template"].create(
            {"name": "Barcoded product", "uom_ids": [Command.link(cls.box.id)]}
        )
        cls.variant = cls.template.product_variant_ids
        cls.packaging = cls.env["product.uom"].create(
            {
                "product_id": cls.variant.id,
                "uom_id": cls.box.id,
                "barcode": "PKG-BOX-12",
            }
        )

    def test_template_action_returns_a_product_scoped_action(self):
        action = self.template.action_open_packaging_barcodes()

        self.assertEqual(action["res_model"], "product.uom")
        self.assertEqual(action["domain"], [("product_id", "in", self.variant.ids)])
        self.assertEqual(action["context"]["default_product_id"], self.variant.id)
        self.assertEqual(action["context"]["product_ids"], self.variant.ids)

    def test_variant_action_returns_a_product_scoped_action(self):
        action = self.variant.action_open_packaging_barcodes()

        self.assertEqual(action["res_model"], "product.uom")
        self.assertEqual(action["domain"], [("product_id", "=", self.variant.id)])
        self.assertEqual(action["context"]["default_product_id"], self.variant.id)

    def test_the_action_domain_selects_this_products_barcodes_only(self):
        other = self.env["product.template"].create(
            {"name": "Other product", "uom_ids": [Command.link(self.box.id)]}
        )
        other_packaging = self.env["product.uom"].create(
            {
                "product_id": other.product_variant_ids.id,
                "uom_id": self.box.id,
                "barcode": "PKG-BOX-12-OTHER",
            }
        )

        action = self.template.action_open_packaging_barcodes()
        found = self.env["product.uom"].search(action["domain"])

        self.assertIn(self.packaging, found)
        self.assertNotIn(other_packaging, found)

    def test_show_variant_name_is_off_for_a_single_variant_product(self):
        action = self.template.action_open_packaging_barcodes()
        self.assertFalse(action["context"]["show_variant_name"])
