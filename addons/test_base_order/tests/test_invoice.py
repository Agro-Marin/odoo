from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestInvoice(BaseOrderTestCase):
    def _line(self, **kw):
        return self._line_on(self._make_order(), **kw)

    def _line_on(self, order, **kw):
        vals = {
            "order_id": order.id,
            "product_id": self.product.id,
            "product_qty": 2.0,
            "price_unit": 50.0,
        }
        vals.update(kw)
        return self.env["base.order.test.line"].create(vals)

    def test_prepare_aml_vals_core_keys(self):
        line = self._line()

        vals = line._prepare_aml_vals()

        self.assertEqual(vals["product_id"], self.product.id)
        self.assertAlmostEqual(vals["price_unit"], 50.0, places=2)
        self.assertEqual(vals["display_type"], "product")
        self.assertEqual(vals["quantity"], line.qty_to_invoice)

    def test_prepare_aml_vals_merges_optional_values(self):
        line = self._line()

        vals = line._prepare_aml_vals(sequence=42)

        self.assertEqual(vals["sequence"], 42)

    def test_create_invoices_returns_move(self):
        order = self._make_order()
        self.env["base.order.test.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_qty": 2.0,
                "price_unit": 50.0,
            }
        )

        moves = order._create_invoices()

        self.assertTrue(moves)
        self.assertEqual(moves.move_type, "out_invoice")
        self.assertEqual(len(moves.invoice_line_ids), 1)

    def test_create_invoices_nothing_to_invoice_raises(self):
        order = self._make_order()  # no lines

        with self.assertRaises(UserError):
            order._create_invoices()

    def test_prepare_down_payment_line_section_values(self):
        order = self._make_order()

        vals = order._prepare_down_payment_line_section_values()

        self.assertEqual(
            vals,
            {
                "order_id": order.id,
                "display_type": "line_section",
                "is_downpayment": True,
                "sequence": 10,
            },
        )
        # The values must be directly usable to create the section line.
        section = self.env["base.order.test.line"].create({**vals, "name": "DP"})
        self.assertEqual(section.display_type, "line_section")
        self.assertTrue(section.is_downpayment)

    def test_down_payment_section_is_created_once_and_reused(self):
        order = self._make_order()

        section = order._get_down_payment_section_line()

        self.assertEqual(section.display_type, "line_section")
        self.assertTrue(section.is_downpayment)
        self.assertEqual(order._get_down_payment_section_line(), section)
        self.assertEqual(
            len(order.line_ids.filtered("is_downpayment")),
            1,
            "the second call must reuse the section, not add another",
        )

    def test_down_payment_section_sorts_after_the_existing_lines(self):
        order = self._make_order()
        self._line_on(order, sequence=42)

        section = order._get_down_payment_section_line()

        self.assertEqual(section.sequence, 43)

    def test_down_payment_lines_follow_their_section(self):
        order = self._make_order()
        self._line_on(order, sequence=5)

        lines = order._create_down_payment_lines(
            [
                {
                    "order_id": order.id,
                    "name": "DP 1",
                    "is_downpayment": True,
                    "price_unit": 10.0,
                },
                {
                    "order_id": order.id,
                    "name": "DP 2",
                    "is_downpayment": True,
                    "price_unit": 20.0,
                },
            ],
        )

        section = order.line_ids.filtered(
            lambda line: line.display_type and line.is_downpayment,
        )
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines.mapped("sequence"),
            [section.sequence + 1, section.sequence + 2],
        )
        self.assertLess(section.sequence, min(lines.mapped("sequence")))

    def test_down_payment_lines_are_attached_to_the_order(self):
        """``_create_order_lines`` links rather than concatenates; the lines
        must still end up on ``line_ids`` — and nothing already there may be
        dropped by the link."""
        order = self._make_order()
        existing = self._line_on(order, sequence=5)

        lines = order._create_down_payment_lines(
            [
                {
                    "order_id": order.id,
                    "name": "DP",
                    "is_downpayment": True,
                    "price_unit": 10.0,
                }
            ],
        )

        self.assertLessEqual(lines, order.line_ids)
        self.assertIn(existing, order.line_ids)

    def test_down_payment_lines_can_be_added_to_a_locked_order(self):
        """Down payments run *after* confirmation, so the order is often locked.

        ``_create_order_lines`` links the new ids onto ``line_ids``, which is an
        order-level x2many write — and ``_validate_write_locked_order`` rejects
        every x2many write on a locked order without inspecting it. The link
        only re-states what the ``create`` already did, so it must not be
        rejected.
        """
        order = self._make_order()
        self._line_on(order, sequence=5)
        order.action_confirm()
        order.action_lock()
        self.assertTrue(order.locked)

        lines = order._create_down_payment_lines(
            [
                {
                    "order_id": order.id,
                    "name": "DP",
                    "is_downpayment": True,
                    "price_unit": 10.0,
                }
            ],
        )

        self.assertLessEqual(lines, order.line_ids)
