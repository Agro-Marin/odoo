from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBillLineMatch(TransactionCase):
    """Bill-to-order matching report and its write-back behaviour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "Match vendor"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Matched part",
                "type": "consu",
                "purchase_ok": True,
                "standard_price": 10.0,
            }
        )
        cls.Match = cls.env["purchase.bill.line.match"]

    def _confirmed_order(self, qty=3, price=10.0):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        order.action_confirm()
        # the report is a SQL view: pending ORM writes must reach the tables
        self.env.flush_all()
        return order

    def _rows(self):
        return self.Match.search([("partner_id", "=", self.vendor.id)])

    def test_confirmed_order_line_awaits_matching(self):
        """A confirmed line with nothing billed yet shows up to be matched."""
        order = self._confirmed_order()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.product_uom_qty, 3.0)
        self.assertEqual(rows.product_uom_price, 10.0)
        self.assertEqual(rows.pol_id, order.line_ids)

    def test_draft_order_is_not_offered_for_matching(self):
        """An unconfirmed order has nothing to reconcile yet (boundary)."""
        self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 2,
                        }
                    )
                ],
            }
        )
        self.env.flush_all()
        self.assertFalse(self._rows())

    def test_editing_the_price_writes_back_to_the_order_line(self):
        """A price corrected in the report reaches the purchase line."""
        order = self._confirmed_order()
        row = self._rows()
        row.product_uom_price = 12.0
        self.assertEqual(order.line_ids.price_unit, 12.0)

    def test_editing_the_quantity_preserves_the_agreed_price(self):
        """Changing the quantity must not silently repriced the line.

        Writing product_qty normally recomputes price_unit from the supplier
        pricelist, which would overwrite a price the buyer agreed on.
        """
        order = self._confirmed_order(qty=3, price=10.0)
        row = self._rows()
        row.product_uom_price = 12.0
        row.product_uom_qty = 5.0
        self.assertEqual(order.line_ids.product_qty, 5.0)
        self.assertEqual(order.line_ids.price_unit, 12.0)

    def test_row_opens_its_purchase_order(self):
        """A row backed by an order line opens that order."""
        order = self._confirmed_order()
        action = self._rows().action_open_line()
        self.assertEqual(action["res_model"], "purchase.order")
        self.assertEqual(action["res_id"], order.id)

    def test_bill_creation_uses_the_lines_currency(self):
        """A bill built from the selection inherits the lines' currency."""
        order = self._confirmed_order()
        action = self.Match._action_create_bill_from_po_lines(
            self.vendor, order.line_ids
        )
        bill = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(bill.move_type, "in_invoice")
        self.assertEqual(bill.partner_id, self.vendor)
        self.assertEqual(bill.currency_id, order.line_ids.currency_id)
        self.assertEqual(bill.invoice_line_ids.product_id, self.product)
