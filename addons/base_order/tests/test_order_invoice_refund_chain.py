from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderInvoiceRefundChain(TransactionCase):
    """`_compute_invoice_ids` must attribute an orphan refund of an orphan
    refund back to the order, not just a single level of reversal."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Refund Chain Partner"})
        cls.product = cls.env["product.product"].create({"name": "Refund Product"})
        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.line = cls.env["sale.order.line"].create(
            {
                "order_id": cls.order.id,
                "product_id": cls.product.id,
                "product_qty": 1.0,
            }
        )
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "sale")], limit=1
        )

    def _invoice(self, move_type, reversed_entry_id=False):
        return self.env["account.move"].create(
            {
                "move_type": move_type,
                "partner_id": self.partner.id,
                "journal_id": self.journal.id,
                "reversed_entry_id": reversed_entry_id,
            }
        )

    def test_two_level_orphan_refund_is_attributed(self):
        invoice = self._invoice("out_invoice")
        self.line.invoice_line_ids = [
            (
                0,
                0,
                {
                    "move_id": invoice.id,
                    "name": "line",
                    "quantity": 1.0,
                    "price_unit": 100.0,
                },
            )
        ]
        # First-level orphan: reverses the real invoice directly, but has no
        # invoice_line_ids of its own linking it back to the order line.
        refund_1 = self._invoice("out_refund", reversed_entry_id=invoice.id)
        # Second-level orphan: reverses the first orphan refund, not the
        # original invoice -- unreachable without following the whole chain.
        refund_2 = self._invoice("out_refund", reversed_entry_id=refund_1.id)

        self.order.invalidate_recordset(["invoice_ids", "invoice_count"])

        self.assertIn(invoice, self.order.invoice_ids)
        self.assertIn(refund_1, self.order.invoice_ids)
        self.assertIn(
            refund_2,
            self.order.invoice_ids,
            "a refund-of-a-refund must still be attributed to the order",
        )
        self.assertEqual(self.order.invoice_count, 3)
