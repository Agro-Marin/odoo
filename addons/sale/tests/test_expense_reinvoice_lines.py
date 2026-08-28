from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExpenseReinvoiceLines(TransactionCase):
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
                            "product_qty": 1,
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
        mapping = dict.fromkeys(lines.ids, order)
        with patch.object(
            type(lines), "_sale_determine_order", lambda records: mapping
        ):
            return lines._sale_create_reinvoice_sale_line()

    def test_cost_becomes_an_expense_line_on_the_order(self):
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
        line = self._cost_line()
        with patch.object(type(line), "_sale_determine_order", lambda records: {}):
            result = line._sale_create_reinvoice_sale_line()
        self.assertFalse(result)

    def test_quotation_must_be_confirmed_before_charging_expenses(self):
        order = self._order(confirm=False)
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_cancelled_order_refuses_the_expense(self):
        order = self._order()
        order._action_cancel()
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_locked_order_refuses_the_expense(self):
        order = self._order()
        order.locked = True
        line = self._cost_line()
        with self.assertRaises(UserError):
            self._reinvoice(line, order)

    def test_identical_costs_share_one_line_when_charged_at_sales_price(self):
        order = self._order()
        merged = self.env["product.product"].create(
            {
                "name": "Merged expense",
                "type": "service",
                "expense_policy": "sales_price",
                "invoice_policy": "transferred",
                "list_price": 100.0,
                "standard_price": 60.0,
            }
        )
        first = self._cost_line(quantity=2, price=60.0, product=merged)
        second = self._cost_line(quantity=3, price=60.0, product=merged)
        lines = first | second
        result = self._reinvoice(lines, order)
        self.assertEqual(
            result[first.id],
            result[second.id],
            "two costs with the same order, product and price must land on one line",
        )

    def test_three_identical_costs_still_share_one_line(self):
        order = self._order()
        merged = self.env["product.product"].create(
            {
                "name": "Merged expense trio",
                "type": "service",
                "expense_policy": "sales_price",
                "invoice_policy": "transferred",
                "list_price": 100.0,
                "standard_price": 60.0,
            }
        )
        costs = self.env["account.move.line"]
        for quantity in (1, 2, 3):
            costs |= self._cost_line(quantity=quantity, price=60.0, product=merged)
        result = self._reinvoice(costs, order)
        self.assertEqual(len({line.id for line in result.values()}), 1)

    def test_distinct_products_do_not_share_a_line(self):
        order = self._order()
        common = {
            "type": "service",
            "expense_policy": "sales_price",
            "invoice_policy": "transferred",
            "standard_price": 60.0,
        }
        one, two = self.env["product.product"].create(
            [
                {"name": "Merged A", "list_price": 100.0, **common},
                {"name": "Merged B", "list_price": 140.0, **common},
            ]
        )
        first = self._cost_line(quantity=1, price=60.0, product=one)
        second = self._cost_line(quantity=1, price=60.0, product=two)
        result = self._reinvoice(first | second, order)
        self.assertNotEqual(result[first.id], result[second.id])

    def test_each_cost_gets_its_own_line_by_default(self):
        order = self._order()
        first = self._cost_line(quantity=2, price=60.0)
        second = self._cost_line(quantity=3, price=60.0)
        lines = first | second
        result = self._reinvoice(lines, order)
        self.assertNotEqual(result[first.id], result[second.id])

    def test_each_expense_line_gets_its_own_sequence(self):
        order = self._order()
        costs = self.env["account.move.line"]
        for quantity in (1, 2, 3):
            costs |= self._cost_line(quantity=quantity, price=60.0)
        result = self._reinvoice(costs, order)
        sequences = [line.sequence for line in result.values()]
        self.assertEqual(
            len(set(sequences)),
            len(sequences),
            "expense lines prepared in one batch must not share a sequence",
        )

    def test_expense_line_lands_after_the_quoted_lines(self):
        order = self._order()
        quoted = order.line_ids[0]
        line = self._cost_line()
        new_line = self._reinvoice(line, order)[line.id]
        self.assertGreater(new_line.sequence, quoted.sequence)
