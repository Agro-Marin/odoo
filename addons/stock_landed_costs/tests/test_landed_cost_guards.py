from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TestStockLandedCostsCommon


@tagged("post_install", "-at_install")
class TestLandedCostGuards(TestStockLandedCostsCommon):
    """Validation guard and cost-line product onchange for stock.landed.cost."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.landed_cost.write(
            {
                "landed_cost_ok": True,
                "categ_id": cls.categ_all.id,
                "type": "service",
                "standard_price": 15.0,
                "split_method_landed_cost": "by_weight",
            }
        )

    def _draft_landed_cost(self):
        return self.env["stock.landed.cost"].create(
            {
                "account_journal_id": self.stock_journal.id,
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.landed_cost.id,
                            "name": "LC line",
                            "price_unit": 15.0,
                            "split_method": "equal",
                            "account_id": self.company_data[
                                "default_account_stock_valuation"
                            ].id,
                        }
                    ),
                ],
            }
        )

    def test_validate_without_target_raises(self):
        """Validating a landed cost with no target picking/move is rejected."""
        landed_cost = self._draft_landed_cost()
        self.assertFalse(landed_cost.picking_ids)
        with self.assertRaises(UserError):
            landed_cost.button_validate()

    def test_cost_line_onchange_product_pulls_defaults(self):
        """Picking a cost-line product fills name, split method, price and account."""
        line = self.env["stock.landed.cost.lines"].new(
            {"product_id": self.landed_cost.id}
        )
        line.onchange_product_id()
        self.assertEqual(line.name, self.landed_cost.name)
        self.assertEqual(line.split_method, "by_weight")
        self.assertAlmostEqual(line.price_unit, 15.0, places=2)
        self.assertEqual(
            line.account_id,
            self.landed_cost.product_tmpl_id.get_product_accounts()["expense"],
        )
