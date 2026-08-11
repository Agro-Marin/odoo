from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExpenseReinvoiceLines(TransactionCase):
    """Creation of the sale lines that charge a vendor cost back to the client.

    ``_sale_determine_order`` is an empty hook here: sale ships the algorithm
    and the downstream modules supply the cost-to-order mapping. The tests
    supply that mapping, which is the contract the hook exists for.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Reinvoiced client"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Reinvoiced expense",
                "type": "service",
                "expense_policy": "cost",
                "list_price": 100.0,
                "standard_price": 60.0,
            }
        )

    def _order(self, confirm=True):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                        }
                    )
                ],
            }
        )
        if confirm:
            order.action_confirm()
        return order

    def _cost_line(self, quantity=2, price=60.0, product=None):
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.customer.id,
                "invoice_date": "2026-08-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": (product or self.product).id,
                            "quantity": quantity,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        return bill.invoice_line_ids[0]

    def _reinvoice(self, lines, order):
        """Run the re-invoicing with the given cost-to-order mapping."""
        mapping = dict.fromkeys(lines.ids, order)
        with patch.object(
            type(lines), "_sale_determine_order", lambda records: mapping
        ):
            return lines._sale_create_reinvoice_sale_line()

    def test_cost_becomes_an_expense_line_on_the_order(self):
        """A mapped cost is charged to the client as an expense line."""
        order = self._order()
        line = self._cost_line(quantity=2, price=60.0)
        result = self._reinvoice(line, order)

        new_line = result[line.id]
        self.assertIn(new_line, order.line_ids)
        self.assertTrue(new_line.is_expense)
        self.assertEqual(new_line.product_id, self.product)
        self.assertEqual(new_line.product_qty, 2.0)
        self.assertEqual(new_line.price_unit, 60.0)
        self.assertEqual(new_line.discount, 0.0)

    def test_cost_mapped_to_nothing_is_not_charged(self):
        """A cost with no order behind it creates no line (negative)."""
        line = self._cost_line()
        with patch.object(type(line), "_sale_determine_order", lambda records: {}):
            result = line._sale_create_reinvoice_sale_line()
        self.assertFalse(result)

    def test_quotation_must_be_confirmed_before_charging_expenses(self):
        """A draft order refuses the expense instead of silently taking it."""
        order = self._order(confirm=False)
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_cancelled_order_refuses_the_expense(self):
        """A cancelled order can no longer accumulate costs (negative)."""
        order = self._order()
        order._action_cancel()
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_locked_order_refuses_the_expense(self):
        """A locked order is closed to new charges (negative)."""
        order = self._order()
        order.locked = True
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_each_cost_gets_its_own_line_by_default(self):
        """Under the cost policy two costs stay two separate charges."""
        order = self._order()
        first = self._cost_line(quantity=2, price=60.0)
        second = self._cost_line(quantity=3, price=60.0)
        lines = first | second
        result = self._reinvoice(lines, order)
        self.assertNotEqual(result[first.id], result[second.id])

    def test_expense_line_lands_after_the_quoted_lines(self):
        """A charged expense is appended below what was quoted."""
        order = self._order()
        quoted = order.line_ids[0]
        line = self._cost_line()
        new_line = self._reinvoice(line, order)[line.id]
        self.assertGreater(new_line.sequence, quoted.sequence)
