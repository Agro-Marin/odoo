from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLandedCostValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cost_product = cls.env["product.product"].create(
            {
                "name": "LC guard product",
                "type": "service",
                "landed_cost_ok": True,
            }
        )

    def _landed_cost(self, price=100.0):
        return self.env["stock.landed.cost"].create(
            {
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": price,
                            "split_method": "equal",
                        }
                    )
                ]
            }
        )

    def test_total_amount_sums_cost_lines(self):
        cost = self._landed_cost(100.0)
        cost.cost_lines = [
            Command.create(
                {
                    "product_id": self.cost_product.id,
                    "price_unit": 50.0,
                    "split_method": "equal",
                }
            )
        ]
        self.assertEqual(cost.amount_total, 150.0)

    def test_validate_non_draft_rejected(self):
        cost = self._landed_cost()
        cost.state = "cancel"
        with self.assertRaises(UserError):
            cost.button_validate()

    def test_validate_without_targets_rejected(self):
        cost = self._landed_cost()
        self.assertFalse(cost.picking_ids)
        with self.assertRaises(UserError):
            cost.button_validate()

    def test_cancel_validated_rejected(self):
        cost = self._landed_cost()
        cost.state = "done"
        with self.assertRaises(UserError):
            cost.button_cancel()

    def test_unlink_validated_rejected(self):
        cost = self._landed_cost()
        cost.state = "done"
        with self.assertRaises(UserError):
            cost.unlink()
