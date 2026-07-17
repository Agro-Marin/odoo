# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for report/wizard/controller layer fixes."""

from collections import defaultdict

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase
from odoo.tools import OrderedSet

from odoo.addons.stock.report.stock_forecasted import ReplenishmentContext


class TestReportWizardFixes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.product = cls.env["product.product"].create(
            {"name": "Report Fix Product", "is_storable": True}
        )

    def _create_move(self, qty, location, location_dest, **extra_vals):
        return self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": location.id,
                "location_dest_id": location_dest.id,
                **extra_vals,
            }
        )

    def test_reception_assign_partially_linked_in_move(self):
        """`action_assign` must only claim the unclaimed part of an in move.

        `in_one` (10 units) already covers 3 units of another out, so only 7
        remain. Assigning an out of 10 against [in_two, in_one] (`in_one`
        iterated first) must draw 7 from `in_one` and continue to `in_two`,
        instead of counting `in_one`'s full 10 and stopping short.
        """
        report = self.env["report.stock.report_reception"]
        out_pre = self._create_move(3, self.stock_location, self.customer_location)
        out = self._create_move(10, self.stock_location, self.customer_location)
        in_one = self._create_move(10, self.supplier_location, self.stock_location)
        in_two = self._create_move(5, self.supplier_location, self.stock_location)
        (out_pre | out | in_one | in_two).write({"state": "confirmed"})
        in_one.move_dest_ids = [Command.link(out_pre.id)]

        # `action_assign` iterates the candidate ins in reverse order.
        report.action_assign([out.id], [10.0], [[in_two.id, in_one.id]])

        self.assertEqual(
            out.move_orig_ids,
            in_one | in_two,
            "The out must be covered by both ins: 7 remaining on the partially"
            " linked one, then 3 from the next one.",
        )
        self.assertEqual(out.procure_method, "make_to_order")
        self.assertEqual(in_one.move_dest_ids, out_pre | out)

    def test_reception_assign_length_mismatch(self):
        """Mismatched assignment arrays must raise instead of truncating."""
        report = self.env["report.stock.report_reception"]
        out = self._create_move(1, self.stock_location, self.customer_location)
        with self.assertRaises(UserError):
            report.action_assign([out.id], [1.0, 2.0], [[]])

    def test_forecasted_reserved_capped_by_remaining_demand(self):
        """`_compute_out_reserved` must not report more reserved than demanded.

        Two linked moves each hold 8 reserved for an out of 10: the reserved
        total must be capped at 10 (8 + 2), not 16, and the on-hand ledger
        must be decremented by exactly that amount.
        """
        report = self.env["stock.forecasted_product_product"]
        out = self._create_move(10, self.stock_location, self.customer_location)
        picks = self.env["stock.move"]
        for __ in range(2):
            pick = self._create_move(8, self.stock_location, self.customer_location)
            pick.quantity = 8.0
            pick.state = "assigned"
            picks |= pick
        ctx = ReplenishmentContext(
            wh_stock_location=self.stock_location,
            wh_stock_sub_location_ids=set(),
            read=True,
            currents=defaultdict(float),
            in_id_to_in_data={},
            ins_per_product=defaultdict(OrderedSet),
            dest_ids_to_in_ids=defaultdict(OrderedSet),
        )

        data = report._compute_out_reserved(out, picks, defaultdict(float), ctx)

        self.assertEqual(data["reserved"], 10.0)
        self.assertEqual(
            ctx.currents[self.product.id, self.stock_location.id],
            -10.0,
            "The on-hand ledger must be decremented by the capped reserved"
            " quantity only.",
        )

    def test_reception_assigned_lines_conserve_quantity(self):
        """`_add_assigned_lines` must allocate, not repeat, the assigned pool.

        One received quantity of 10 chained to two outs of 10 each must render
        assigned lines totalling 10, not 10 per out.
        """
        report = self.env["report.stock.report_reception"]
        outs = self.env["stock.move"]
        for __ in range(2):
            picking = self.env["stock.picking"].create(
                {
                    "picking_type_id": self.warehouse.out_type_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                }
            )
            outs |= self._create_move(
                10,
                self.stock_location,
                self.customer_location,
                picking_id=picking.id,
            )
        in_move = self._create_move(10, self.supplier_location, self.stock_location)
        (outs | in_move).write({"state": "confirmed"})
        in_move.move_dest_ids = [Command.set(outs.ids)]

        sources_to_lines = defaultdict(list)
        report._add_assigned_lines(
            sources_to_lines, {self.product: [10.0, [in_move.id]]}
        )

        lines = [line for lines in sources_to_lines.values() for line in lines]
        self.assertEqual(
            sum(line["quantity"] for line in lines),
            10.0,
            "Assigned lines must never total more than the received quantity.",
        )
        self.assertTrue(all(line["is_assigned"] for line in lines))

    def test_return_wizard_no_returnable_moves(self):
        """A done picking with no returnable move must raise a clear error.

        Moves whose destination is an inventory location are excluded from the
        return wizard; a picking made only of those must surface the "No
        products to return" error instead of an empty wizard.
        """
        inventory_location = self.env["stock.location"].search(
            [
                ("usage", "=", "inventory"),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.int_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": inventory_location.id,
            }
        )
        move = self._create_move(
            5,
            self.stock_location,
            inventory_location,
            picking_id=picking.id,
        )
        picking.action_confirm()
        move.quantity = 5.0
        move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")

        with self.assertRaises(UserError):
            self.env["stock.return.picking"].with_context(
                active_id=picking.id,
                active_ids=picking.ids,
                active_model="stock.picking",
            ).create({})
