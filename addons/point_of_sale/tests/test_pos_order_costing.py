# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_anglo_saxon import TestAngloSaxonCommon


@tagged("post_install", "-at_install")
class TestPosOrderCosting(TestAngloSaxonCommon):
    """Anglo-saxon COGS valuation and refund accounting on pos.order[.line]."""

    def _make_order(self, qty=1.0, price=450.0, **order_vals):
        vals = {
            "company_id": self.company.id,
            "partner_id": self.partner.id,
            "pricelist_id": self.company.partner_id.property_product_pricelist.id,
            "session_id": self.pos_config.current_session_id.id,
            "lines": [
                (
                    0,
                    0,
                    {
                        "name": "OL/0001",
                        "product_id": self.product.id,
                        "price_unit": price,
                        "discount": 0.0,
                        "qty": qty,
                        "price_subtotal": qty * price,
                        "price_subtotal_incl": qty * price,
                    },
                )
            ],
            "amount_total": qty * price,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
            "last_order_preparation_change": "{}",
        }
        vals.update(order_vals)
        return self.PosOrder.create(vals)

    def _pay(self, order):
        ctx = {"active_ids": order.ids, "active_id": order.id}
        payment = self.PosMakePayment.with_context(**ctx).create(
            {
                "amount": order.amount_total,
                "payment_method_id": self.cash_payment_method.id,
            }
        )
        payment.with_context(**ctx).check()

    def _open_session(self):
        self.pos_config.open_ui()
        self.pos_config.current_session_id.set_opening_control(0, None)

    # Defect 1 -- COGS collapsing to 0

    def test_cogs_falls_back_when_no_valued_move(self):
        """A ship-later invoiced order must still book COGS.

        The delivery is not done at invoicing time, so no move passes the
        `is_valued` filter and `_get_pos_anglo_saxon_price_unit` returns 0.
        That 0 used to overwrite the value `super()` had already computed,
        leaving the expense account undebited and the interim account
        uncleared.
        """
        self._open_session()
        order = self._make_order(to_invoice=True, shipping_date="2030-01-01")
        self._pay(order)

        invoice = order.account_move
        self.assertTrue(invoice, "the order should have produced an invoice")

        cogs_line = invoice.line_ids.filtered(
            lambda l: (
                l.display_type == "cogs"
                and l.account_id == self.category.property_account_expense_categ_id
            )
        )
        self.assertTrue(cogs_line, "no COGS line was generated for the invoice")
        self.assertEqual(
            cogs_line.debit,
            self.product.standard_price,
            "COGS must fall back to the standard valuation when the POS "
            "picking has no valued move yet",
        )

    def test_pos_anglo_saxon_price_unit_returns_zero_without_valued_move(self):
        """Precondition of the fallback above: the POS helper yields 0 here."""
        self._open_session()
        order = self._make_order(to_invoice=True, shipping_date="2030-01-01")
        self._pay(order)

        moves = order.mapped("picking_ids.move_ids").filtered(
            lambda m: m.product_id == self.product
        )
        self.assertTrue(moves, "the ship-later rule should have created a move")
        self.assertFalse(any(moves.mapped("is_valued")))
        self.assertEqual(
            order.sudo()._get_pos_anglo_saxon_price_unit(
                self.product, self.partner.id, 1.0
            ),
            0,
        )

    def test_cogs_uses_pos_valuation_when_delivery_is_done(self):
        """The fallback must not shadow a genuine POS valuation."""
        self.product.categ_id.property_cost_method = "fifo"
        self.product.standard_price = 5.0
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "inventory_quantity": 5.0,
                "location_id": self.warehouse.lot_stock_id.id,
            }
        ).action_apply_inventory()
        # Second, cheaper layer: a FIFO sale of 7 spans both (5*5 + 2*1 = 27).
        self.product.standard_price = 1.0
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "inventory_quantity": 10.0,
                "location_id": self.warehouse.lot_stock_id.id,
            }
        ).action_apply_inventory()

        self._open_session()
        order = self._make_order(qty=7.0, to_invoice=True)
        self._pay(order)

        cogs_line = order.account_move.line_ids.filtered(
            lambda l: (
                l.debit
                and l.account_id == self.category.property_account_expense_categ_id
            )
        )
        self.assertEqual(
            cogs_line.debit,
            27,
            "the real FIFO cost of the delivered goods, not standard_price",
        )

    # Defect 2 -- PosOrderLine.write must be batch-safe

    def test_write_qty_on_several_lines(self):
        self.pos_config.order_edit_tracking = True
        self._open_session()
        order = self._make_order(qty=5.0)
        order.write(
            {
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/0002",
                            "product_id": self.product.id,
                            "price_unit": 450,
                            "qty": 5.0,
                            "price_subtotal": 2250,
                            "price_subtotal_incl": 2250,
                        },
                    )
                ]
            }
        )
        self.assertEqual(len(order.lines), 2)

        # Used to raise "Expected singleton" on the multi-record qty comparison.
        order.lines.write({"qty": 3.0})

        self.assertEqual(order.lines.mapped("qty"), [3.0, 3.0])
        self.assertTrue(
            all(order.lines.mapped("is_edited")),
            "every reduced line must be flagged, not just the first",
        )

    def test_write_qty_increase_is_not_flagged(self):
        self.pos_config.order_edit_tracking = True
        self._open_session()
        order = self._make_order(qty=1.0)
        order.lines.write({"qty": 4.0})
        self.assertFalse(order.lines.is_edited)

    # Defect 3 -- the removed pack_lot_line_ids branch

    def test_pack_lot_line_ids_is_not_a_field(self):
        """Guards the dead `write` branch that keyed on this name.

        It never fired, and its body iterated `pack_lot_ids` instead, so it
        would have raised TypeError if it ever had. The client sends no
        `server_id` on lot lines, so the branch was removed rather than
        repaired; reinstating it needs this assertion to change first.
        """
        self.assertNotIn("pack_lot_line_ids", self.env["pos.order.line"]._fields)

    # Defect 4 -- cancelled refunds must not be counted

    def test_refund_orders_count_excludes_cancelled(self):
        self._open_session()
        order = self._make_order()
        self._pay(order)

        refund = self.PosOrder.browse(order.refund()["res_id"])
        order.invalidate_recordset()
        self.assertEqual(order.refund_orders_count, 1)
        self.assertEqual(order.lines.refunded_qty, 1.0)

        refund.action_pos_order_cancel()
        order.invalidate_recordset()
        self.assertEqual(refund.state, "cancel")
        self.assertEqual(
            order.refund_orders_count,
            0,
            "a cancelled refund refunds nothing and must not be counted",
        )
        self.assertEqual(order.lines.refunded_qty, 0.0)
        self.assertNotIn(
            refund.id,
            order.action_view_refund_orders()["domain"][0][2],
            "the smart button must not open cancelled refunds",
        )

    # Defect 5 -- refunded_qty must react to the refund line's qty

    def test_refunded_qty_depends_on_refund_line_qty(self):
        self._open_session()
        order = self._make_order(qty=5.0)
        self._pay(order)

        refund = self.PosOrder.browse(order.refund()["res_id"])
        order.invalidate_recordset()
        self.assertEqual(order.lines.refunded_qty, 5.0)

        # No explicit invalidation: the depends must cover `qty` itself.
        refund.lines.write({"qty": -2.0})
        self.assertEqual(order.lines.refunded_qty, 2.0)
