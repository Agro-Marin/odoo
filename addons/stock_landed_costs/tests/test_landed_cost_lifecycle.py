from odoo import Command
from odoo.tests import tagged

from .common import TestStockLandedCostsCommon


@tagged("post_install", "-at_install")
class TestLandedCostLifecycle(TestStockLandedCostsCommon):
    def _landed_cost(self, price_units):
        return self.env["stock.landed.cost"].create(
            {
                "account_journal_id": self.stock_journal.id,
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.landed_cost.id,
                            "name": "LC line",
                            "price_unit": price_unit,
                            "split_method": "equal",
                            "account_id": self.company_data[
                                "default_account_stock_valuation"
                            ].id,
                        }
                    )
                    for price_unit in price_units
                ],
            }
        )

    def test_compute_total_amount_sums_cost_lines(self):
        landed_cost = self._landed_cost([30.0, 20.0])
        self.assertAlmostEqual(landed_cost.amount_total, 50.0, places=2)

    def test_unlink_draft_cancels_then_removes(self):
        landed_cost = self._landed_cost([10.0])
        self.assertEqual(landed_cost.state, "draft")
        landed_cost.unlink()
        self.assertFalse(landed_cost.exists())

    def _incoming_picking(self, product):
        picking = self.Picking.create(
            {
                "partner_id": self.supplier_id,
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.supplier_location_id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }
        )
        self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 1,
                "product_uom_id": product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.supplier_location_id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }
        )
        return picking

    def test_pickings_count_follows_the_linked_transfers(self):
        landed_cost = self._landed_cost([10.0])
        self.assertEqual(landed_cost.pickings_count, 0)

        first = self._incoming_picking(self.product_refrigerator)
        second = self._incoming_picking(self.product_oven)
        landed_cost.picking_ids = first + second
        self.assertEqual(landed_cost.pickings_count, 2)

        landed_cost.picking_ids = first
        self.assertEqual(
            landed_cost.pickings_count,
            1,
            "the count must follow picking_ids, not go stale on it",
        )

    def test_action_view_pickings_opens_the_only_transfer_in_form(self):
        landed_cost = self._landed_cost([10.0])
        picking = self._incoming_picking(self.product_refrigerator)
        landed_cost.picking_ids = picking

        action = landed_cost.action_view_pickings()

        self.assertEqual(action["res_model"], "stock.picking")
        self.assertEqual(action["res_id"], picking.id)
        self.assertEqual(action["views"], [(False, "form")])

    def test_action_view_pickings_lists_several_transfers(self):
        landed_cost = self._landed_cost([10.0])
        pickings = self._incoming_picking(
            self.product_refrigerator
        ) + self._incoming_picking(self.product_oven)
        landed_cost.picking_ids = pickings

        action = landed_cost.action_view_pickings()

        self.assertEqual(action["res_model"], "stock.picking")
        self.assertNotIn("res_id", action)
        self.assertEqual(action["domain"], [("id", "in", pickings.ids)])
