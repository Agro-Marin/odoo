from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale_management.tests.common import SaleManagementCommon


@tagged("post_install", "-at_install")
class TestQuotationTemplateConfiguredProduct(SaleManagementCommon):
    """A quotation template line remembers how the product was configured."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.embroidery = cls.env["product.attribute"].create(
            {
                "name": "Embroidery",
                "create_variant": "no_variant",
                "value_ids": [
                    Command.create({"name": "Initials"}),
                    Command.create({"name": "Logo"}),
                    Command.create({"name": "Your own text", "is_custom": True}),
                ],
            }
        )
        cls.shirt = cls.env["product.template"].create(
            {
                "name": "Embroidered shirt",
                "list_price": 30.0,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": cls.embroidery.id,
                            "value_ids": [Command.set(cls.embroidery.value_ids.ids)],
                        }
                    ),
                ],
            }
        )
        ptavs = cls.shirt.attribute_line_ids.product_template_value_ids
        cls.ptav_initials = ptavs.filtered(lambda v: v.name == "Initials")
        cls.ptav_own_text = ptavs.filtered(lambda v: v.name == "Your own text")
        cls.shirt_variant = cls.shirt.product_variant_id

    def _create_template(self, line_values):
        return self.env["sale.order.template"].create(
            {
                "name": "Shirt template",
                "sale_order_template_line_ids": [
                    Command.create(
                        {
                            "product_id": self.shirt_variant.id,
                            "product_uom_qty": 2.0,
                            **line_values,
                        }
                    ),
                ],
            }
        )

    def _order_from(self, template):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        order.sale_order_template_id = template
        order._onchange_sale_order_template_id()
        return order

    def test_a_template_line_keeps_the_no_variant_value_it_was_configured_with(self):
        template = self._create_template(
            {
                "product_no_variant_attribute_value_ids": [
                    Command.set(self.ptav_initials.ids)
                ],
            }
        )
        line = template.sale_order_template_line_ids

        self.assertEqual(
            line.product_no_variant_attribute_value_ids, self.ptav_initials
        )
        self.assertTrue(line.is_configurable_product)

    def test_the_configured_value_reaches_the_quotation(self):
        template = self._create_template(
            {
                "product_no_variant_attribute_value_ids": [
                    Command.set(self.ptav_initials.ids)
                ],
            }
        )

        order_line = self._order_from(template).line_ids

        self.assertEqual(
            order_line.product_no_variant_attribute_value_ids, self.ptav_initials
        )

    def test_a_custom_value_reaches_the_quotation(self):
        template = self._create_template(
            {
                "product_no_variant_attribute_value_ids": [
                    Command.set(self.ptav_own_text.ids)
                ],
                "product_custom_attribute_value_ids": [
                    Command.create(
                        {
                            "custom_product_template_attribute_value_id": (
                                self.ptav_own_text.id
                            ),
                            "custom_value": "Jem",
                        }
                    ),
                ],
            }
        )

        order_line = self._order_from(template).line_ids

        self.assertEqual(
            order_line.product_custom_attribute_value_ids.custom_value, "Jem"
        )
        self.assertEqual(
            order_line.product_custom_attribute_value_ids.custom_product_template_attribute_value_id,
            self.ptav_own_text,
        )

    def test_changing_the_product_drops_the_values_that_no_longer_apply(self):
        template = self._create_template(
            {
                "product_no_variant_attribute_value_ids": [
                    Command.set(self.ptav_own_text.ids)
                ],
                "product_custom_attribute_value_ids": [
                    Command.create(
                        {
                            "custom_product_template_attribute_value_id": (
                                self.ptav_own_text.id
                            ),
                            "custom_value": "Jem",
                        }
                    ),
                ],
            }
        )
        line = template.sale_order_template_line_ids

        line.product_id = self.product

        self.assertFalse(line.product_no_variant_attribute_value_ids)
        self.assertFalse(line.product_custom_attribute_value_ids)
        self.assertFalse(line.is_configurable_product)

    def test_a_plain_template_line_still_carries_no_configuration(self):
        template = self._create_template({"product_id": self.product.id})

        order_line = self._order_from(template).line_ids

        self.assertFalse(order_line.product_no_variant_attribute_value_ids)
        self.assertFalse(order_line.product_custom_attribute_value_ids)
