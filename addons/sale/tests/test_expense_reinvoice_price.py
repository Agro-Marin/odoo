from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExpenseReinvoicePrice(TransactionCase):
    """Price at which a vendor cost is re-invoiced to the customer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Reinvoiced client"})
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.customer.id,
            }
        )

    def _bill_line(self, product, quantity=2, price=60.0):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.customer.id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "quantity": quantity,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        return bill.invoice_line_ids[0]

    def _product(self, policy="sales_price", list_price=100.0, cost=60.0):
        return self.env["product.product"].create(
            {
                "name": f"Expense {policy}",
                "type": "service",
                "expense_policy": policy,
                "list_price": list_price,
                "standard_price": cost,
            }
        )

    def test_sales_price_policy_charges_the_catalog_price(self):
        """With the sales-price policy the customer pays the list price."""
        line = self._bill_line(self._product("sales_price"))
        self.assertEqual(line._sale_get_invoice_price(self.order), 100.0)

    def test_cost_policy_charges_what_was_actually_paid(self):
        """With the cost policy the customer pays the incurred amount."""
        line = self._bill_line(self._product("cost"), quantity=2, price=60.0)
        self.assertEqual(line._sale_get_invoice_price(self.order), 60.0)

    def test_cost_policy_divides_the_total_by_the_quantity(self):
        """The re-invoiced unit price comes from amount over quantity."""
        line = self._bill_line(self._product("cost"), quantity=4, price=25.0)
        self.assertEqual(line._sale_get_invoice_price(self.order), 25.0)

    def test_zero_quantity_never_divides(self):
        """A zero-quantity line prices at zero instead of dividing (boundary)."""
        line = self._bill_line(self._product("cost"), quantity=0, price=60.0)
        self.assertEqual(line._sale_get_invoice_price(self.order), 0.0)

    def test_line_with_a_policy_is_reinvoiceable(self):
        """A cost carrying a re-invoice policy is picked up for the order."""
        line = self._bill_line(self._product("cost"))
        self.assertTrue(line._sale_can_be_reinvoice())

    def test_line_without_a_policy_is_not_reinvoiceable(self):
        """A product with no policy is never re-invoiced (negative)."""
        line = self._bill_line(self._product("no"))
        self.assertFalse(line._sale_can_be_reinvoice())

    def test_line_already_tied_to_an_order_is_not_reinvoiced_twice(self):
        """A cost already linked to a sale line is never charged again."""
        product = self._product("cost")
        line = self._bill_line(product)
        order_line = self.env["sale.order.line"].create(
            {
                "order_id": self.order.id,
                "product_id": product.id,
                "product_uom_qty": 1,
            }
        )
        line.sale_line_ids = [Command.set(order_line.ids)]
        self.assertFalse(line._sale_can_be_reinvoice())
