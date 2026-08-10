from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestInvoice(BaseOrderTestCase):
    def _line(self, **kw):
        order = self._make_order()
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
            },
        )
        # The values must be directly usable to create the section line.
        section = self.env["base.order.test.line"].create({**vals, "name": "DP"})
        self.assertEqual(section.display_type, "line_section")
        self.assertTrue(section.is_downpayment)
