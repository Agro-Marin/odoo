from odoo.fields import Command
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestDocumentMatch(BaseOrderTestCase):
    """`mixin.order.document.match`: orders and invoices in one list.

    A SQL view putting posted invoices beside confirmed orders that still owe
    an invoice, so whoever reconciles the two sees both without switching
    screens. Both shipping models live in `sale` and `purchase`.
    """

    def _rows(self, orders=None, moves=None):
        self.env.flush_all()
        self.env.invalidate_all()
        return self.env["base.order.test.document.match"].search(
            [
                "|",
                ("order_id", "in", orders.ids if orders else []),
                ("move_id", "in", moves.ids if moves else []),
            ]
        )

    def _confirmed_order(self, price=100.0, ref=None):
        order = self._make_order(partner_ref=ref) if ref else self._make_order()
        self._make_line(order=order, product_qty=1.0, price_unit=price)
        order.action_confirm()
        return order

    def _posted_invoice(self, price=100.0, ref=None):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "ref": ref,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": 1.0,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        move.action_post()
        return move

    def test_a_confirmed_order_owing_an_invoice_is_listed(self):
        order = self._confirmed_order()

        rows = self._rows(order)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.order_id, order)
        self.assertFalse(rows.move_id)

    def test_a_draft_order_is_not_listed(self):
        order = self._make_order()
        self._make_line(order=order)

        self.assertFalse(self._rows(order))

    def test_a_posted_invoice_is_listed(self):
        move = self._posted_invoice()

        rows = self._rows(moves=move)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.move_id, move)
        self.assertFalse(rows.order_id)

    def test_a_draft_invoice_is_not_listed(self):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_line_ids": [
                    Command.create({"product_id": self.product.id, "quantity": 1.0})
                ],
            }
        )

        self.assertFalse(self._rows(moves=move))

    def test_an_order_already_fully_invoiced_leaves_the_list(self):
        """The view is for what still owes an invoice."""
        order = self._make_order()
        self._make_line(
            order=order,
            product_qty=1.0,
            price_unit=100.0,
            qty_invoiced_input=1.0,
        )
        order.action_confirm()
        self.assertEqual(order.invoice_state, "done")

        self.assertFalse(self._rows(order))

    def test_the_two_sides_keep_apart_in_one_id_space(self):
        order = self._confirmed_order()
        move = self._posted_invoice()

        rows = self._rows(order, move)

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.id < 0 for r in rows.filtered("order_id")))
        self.assertTrue(all(r.id > 0 for r in rows.filtered("move_id")))

    def test_a_row_carries_the_amount_of_the_document_it_came_from(self):
        order = self._confirmed_order(price=250.0)
        move = self._posted_invoice(price=310.0)

        rows = self._rows(order, move)

        self.assertAlmostEqual(rows.filtered("order_id").amount, 250.0, places=2)
        self.assertAlmostEqual(rows.filtered("move_id").amount, 310.0, places=2)

    def test_a_row_carries_the_reference_of_its_own_side(self):
        order = self._confirmed_order(ref="ORDER-REF")
        move = self._posted_invoice(ref="INVOICE-REF")

        rows = self._rows(order, move)

        self.assertEqual(rows.filtered("order_id").reference, "ORDER-REF")
        self.assertEqual(rows.filtered("move_id").reference, "INVOICE-REF")

    def test_the_display_name_reads_name_reference_and_amount(self):
        order = self._confirmed_order(price=250.0, ref="ORDER-REF")

        row = self._rows(order)

        self.assertIn(order.name, row.display_name)
        self.assertIn("ORDER-REF", row.display_name)
        self.assertIn("250", row.display_name)

    def test_an_order_with_nothing_to_invoice_shows_a_zero_amount(self):
        """`invoice_state == 'no'` means the amount on the row is not owed."""
        order = self._make_order()
        self._make_line(order=order, product_qty=0.0, price_unit=100.0)
        order.action_confirm()
        self.assertEqual(order.invoice_state, "no")

        row = self._rows(order)

        self.assertTrue(row)
        self.assertIn("0.00", row.display_name)
