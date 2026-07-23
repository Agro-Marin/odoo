# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import tagged

from .common import TestStockLandedCostsCommon


@tagged("post_install", "-at_install")
class TestLandedCostLifecycle(TestStockLandedCostsCommon):
    """stock.landed.cost record-level helpers: total amount and draft removal."""

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
        """amount_total is the sum of the cost lines' price units."""
        landed_cost = self._landed_cost([30.0, 20.0])
        self.assertAlmostEqual(landed_cost.amount_total, 50.0, places=2)

    def test_unlink_draft_cancels_then_removes(self):
        """Unlinking a draft landed cost cancels it and deletes the record."""
        landed_cost = self._landed_cost([10.0])
        self.assertEqual(landed_cost.state, "draft")
        landed_cost.unlink()
        self.assertFalse(landed_cost.exists())
