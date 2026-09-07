from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestProductCatalogPreviouslyBought(SaleCommon):
    """Narrowing the catalog to what this customer has bought before.

    754 of our variants are saleable, and the customers that carry the volume
    buy between 11 and 137 distinct products each, over and over. The filter
    is how a salesperson gets from the first number to the second.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_partner = cls.env["res.partner"].create(
            {"name": "Second Customer"},
        )
        # `cls.partner` bought `cls.product` once, and has `cls.sale_order`
        # still in draft with `cls.service_product` on it.
        cls.past_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 1.0,
                        },
                    ),
                ],
            },
        )
        cls.past_order.action_confirm()
        cls.new_order = cls.env["sale.order"].create(
            {"partner_id": cls.partner.id},
        )
        cls.other_order = cls.env["sale.order"].create(
            {"partner_id": cls.other_partner.id},
        )

    def _catalog_of(self, order):
        """What the "Previously bought" filter returns in `order`'s catalog."""
        context = order.action_add_from_catalog()["context"]
        return (
            self.env["product.product"]
            .with_context(**context)
            .search([("previously_bought_by_customer", "=", True)])
        )

    def test_the_filter_keeps_what_this_customer_bought(self):
        self.assertIn(self.product, self._catalog_of(self.new_order))

    def test_the_filter_drops_what_this_customer_never_bought(self):
        self.assertNotIn(self.service_product, self._catalog_of(self.new_order))

    def test_a_draft_order_is_not_a_purchase(self):
        """`cls.sale_order` carries `service_product` and is still a quotation,
        so it must not put the product in the customer's history."""
        self.assertEqual(self.sale_order.state, "draft")
        self.assertIn(self.service_product, self.sale_order.line_ids.product_id)
        self.assertNotIn(self.service_product, self._catalog_of(self.new_order))

    def test_another_customers_history_does_not_leak(self):
        self.assertFalse(self._catalog_of(self.other_order))

    def test_outside_a_catalog_the_filter_matches_nothing(self):
        """No order in the context means no customer, and a filter with no
        customer must not silently return the whole catalog."""
        self.assertFalse(
            self.env["product.product"].search(
                [("previously_bought_by_customer", "=", True)],
            ),
        )
