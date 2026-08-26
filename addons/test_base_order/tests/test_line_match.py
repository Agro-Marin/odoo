from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestLineMatch(BaseOrderTestCase):
    """`mixin.order.line.match.action_match_lines`.

    A SQL view unions open order lines with invoice lines that are not linked
    to any, and this writes the links between them. Every shipping model
    carrying the mixin lives in `sale` or `purchase`, so the algorithm ran in
    production and was asserted by nothing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_product = cls.env["product.product"].create(
            {"name": "BO Other Product", "list_price": 40.0}
        )

    def _confirmed_order(self, *lines):
        order = self._make_order()
        for product, qty, price in lines:
            self.env["base.order.test.line"].create(
                {
                    "order_id": order.id,
                    "product_id": product.id,
                    "product_qty": qty,
                    "price_unit": price,
                    "name": product.name,
                }
            )
        order.action_confirm()
        return order

    def _invoice(self, *lines):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "quantity": qty,
                            "price_unit": price,
                        }
                    )
                    for product, qty, price in lines
                ],
            }
        )

    def _rows(self, order=None, move=None):
        self.env.flush_all()
        self.env.invalidate_all()
        Match = self.env["base.order.test.line.match"]
        domain = []
        if order and move:
            domain = [
                "|",
                ("order_id", "=", order.id),
                ("account_move_id", "=", move.id),
            ]
        elif order:
            domain = [("order_id", "=", order.id)]
        elif move:
            domain = [("account_move_id", "=", move.id)]
        return Match.search(domain)

    # ─── the view itself ──────────────────────────────────────────

    def test_the_view_carries_both_sides(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))

        rows = self._rows(order, move)

        self.assertEqual(len(rows.filtered("order_line_id")), 1)
        self.assertEqual(len(rows.filtered("aml_id")), 1)

    def test_order_line_rows_have_a_positive_id_and_invoice_rows_a_negative_one(self):
        """The union has to keep the two sides apart in one id space."""
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))

        rows = self._rows(order, move)

        self.assertTrue(all(r.id > 0 for r in rows.filtered("order_line_id")))
        self.assertTrue(all(r.id < 0 for r in rows.filtered("aml_id")))

    def test_a_linked_invoice_line_leaves_the_view(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))
        self._rows(order, move).action_match_lines()

        remaining = self._rows(move=move)

        self.assertFalse(remaining.filtered("aml_id"))

    # ─── matching ─────────────────────────────────────────────────

    def test_matching_links_the_invoice_line_to_the_order_line(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))

        self._rows(order, move).action_match_lines()
        self.env.invalidate_all()

        self.assertEqual(order.line_ids.invoice_line_ids, move.invoice_line_ids)
        self.assertEqual(order.invoice_ids, move)

    def test_matching_pairs_same_product_lines_by_equal_unit_price(self):
        order = self._confirmed_order(
            (self.product, 1.0, 10.0),
            (self.product, 1.0, 70.0),
        )
        move = self._invoice(
            (self.product, 1.0, 70.0),
            (self.product, 1.0, 10.0),
        )

        self._rows(order, move).action_match_lines()
        self.env.invalidate_all()

        for line in order.line_ids:
            with self.subTest(price=line.price_unit):
                self.assertEqual(len(line.invoice_line_ids), 1)
                self.assertAlmostEqual(
                    line.invoice_line_ids.price_unit,
                    line.price_unit,
                    places=2,
                )

    def test_lines_of_different_products_are_not_matched_to_each_other(self):
        """Matching is per product; what is left over goes down the residue
        path, so the order line still reaches the invoice -- as its own new
        line, never linked to the unrelated one that was already there."""
        order = self._confirmed_order((self.product, 1.0, 10.0))
        move = self._invoice((self.other_product, 1.0, 10.0))
        pre_existing = move.invoice_line_ids

        self._rows(order, move).action_match_lines()
        self.env.invalidate_all()

        linked = order.line_ids.invoice_line_ids
        self.assertNotIn(pre_existing, linked)
        self.assertEqual(linked.product_id, self.product)

    def test_selecting_no_order_line_is_refused(self):
        move = self._invoice((self.product, 5.0, 10.0))
        rows = self._rows(move=move)

        with self.assertRaises(UserError):
            rows.action_match_lines()

    def test_order_lines_alone_open_a_new_invoice(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        rows = self._rows(order=order)

        action = rows.action_match_lines()

        self.assertEqual(action["res_model"], "account.move")

    # ─── the residue ──────────────────────────────────────────────

    def test_an_unmatched_order_line_is_added_to_the_invoice(self):
        order = self._confirmed_order(
            (self.product, 1.0, 10.0),
            (self.other_product, 1.0, 40.0),
        )
        move = self._invoice((self.product, 1.0, 10.0))

        self._rows(order, move).action_match_lines()
        self.env.invalidate_all()

        self.assertIn(
            self.other_product,
            move.invoice_line_ids.product_id,
            "the order line with no counterpart should land on the invoice",
        )

    def test_an_unmatched_invoice_line_is_removed(self):
        order = self._confirmed_order((self.product, 1.0, 10.0))
        move = self._invoice(
            (self.product, 1.0, 10.0),
            (self.other_product, 1.0, 40.0),
        )

        self._rows(order, move).action_match_lines()
        self.env.invalidate_all()

        self.assertNotIn(self.other_product, move.invoice_line_ids.product_id)

    # ─── navigation ───────────────────────────────────────────────

    def test_opening_a_row_goes_to_the_document_it_came_from(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))
        rows = self._rows(order, move)

        order_row = rows.filtered("order_line_id")[0]
        invoice_row = rows.filtered("aml_id")[0]

        self.assertEqual(order_row.action_open_line()["res_model"], "base.order.test")
        self.assertEqual(invoice_row.action_open_line()["res_model"], "account.move")

    def test_a_row_reports_the_reference_of_its_own_side(self):
        order = self._confirmed_order((self.product, 5.0, 10.0))
        move = self._invoice((self.product, 5.0, 10.0))
        rows = self._rows(order, move)

        self.assertEqual(
            rows.filtered("order_line_id")[0].reference, order.display_name
        )
        self.assertEqual(rows.filtered("aml_id")[0].reference, move.display_name)

    def test_amounts_are_reported_on_the_side_that_owns_them(self):
        order = self._confirmed_order((self.product, 2.0, 10.0))
        move = self._invoice((self.product, 2.0, 10.0))
        rows = self._rows(order, move)

        order_row = rows.filtered("order_line_id")[0]
        invoice_row = rows.filtered("aml_id")[0]

        self.assertTrue(order_row.ordered_amount_taxexc)
        self.assertFalse(order_row.invoiced_amount_taxexc)
        self.assertTrue(invoice_row.invoiced_amount_taxexc)
        self.assertFalse(invoice_row.ordered_amount_taxexc)
