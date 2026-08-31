from odoo.tests import tagged

from .common import TestStockLandedCostsCommon


@tagged("post_install", "-at_install")
class TestAccountMoveLineLandedCost(TestStockLandedCostsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.landed_cost.write(
            {
                "landed_cost_ok": True,
                "categ_id": cls.categ_all.id,
                "type": "service",
            }
        )

    def test_onchange_product_flags_landed_cost_line(self):
        line = self.env["account.move.line"].new({"product_id": self.landed_cost.id})
        line._onchange_product_id_landed_costs()
        self.assertTrue(line.is_landed_costs_line)

    def test_onchange_product_clears_flag_for_regular_product(self):
        line = self.env["account.move.line"].new(
            {"product_id": self.product_refrigerator.id}
        )
        line._onchange_product_id_landed_costs()
        self.assertFalse(line.is_landed_costs_line)

    def test_onchange_flag_reset_for_non_service_product(self):
        line = self.env["account.move.line"].new(
            {
                "product_id": self.product_refrigerator.id,
                "is_landed_costs_line": True,
            }
        )
        line._onchange_is_landed_costs_line()
        self.assertFalse(line.is_landed_costs_line)

    def test_service_landed_cost_is_stock_account_eligible(self):
        line = self.env["account.move.line"].new({"product_id": self.landed_cost.id})
        self.assertTrue(line._eligible_for_stock_account())
