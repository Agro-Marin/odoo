"""Tests for the manufacturing target on landed costs."""

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoLandedCost(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cost_product = cls.env["product.product"].create(
            {"name": "MRP LC product", "type": "service", "landed_cost_ok": True}
        )

    def _landed_cost(self, target_model="manufacturing"):
        return self.env["stock.landed.cost"].create(
            {
                "target_model": target_model,
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": 100.0,
                            "split_method": "equal",
                        }
                    )
                ],
            }
        )

    def test_onchange_clears_mo_when_not_manufacturing(self):
        """Switching away from manufacturing clears the MO selection."""
        cost = self._landed_cost(target_model="picking")
        cost._onchange_target_model()
        self.assertFalse(cost.mrp_production_ids)

    def test_targeted_moves_empty_without_mo(self):
        """The targeted-move helper runs and returns no moves without an MO."""
        cost = self._landed_cost(target_model="manufacturing")
        self.assertFalse(cost._get_targeted_move_ids())
