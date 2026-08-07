# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyReward(TransactionCase):
    """loyalty.reward global-discount classification."""

    def _reward(self, applicability):
        program = self.env["loyalty.program"].create(
            {
                "name": f"Program {applicability}",
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_applicability": applicability,
                            "discount_mode": "percent",
                        },
                    )
                ],
            }
        )
        return program.reward_ids

    def test_order_discount_is_global(self):
        """An order-wide percentage discount is a global discount."""
        self.assertTrue(self._reward("order").is_global_discount)

    def test_cheapest_discount_is_not_global(self):
        """A cheapest-product discount is not a global discount (boundary)."""
        self.assertFalse(self._reward("cheapest").is_global_discount)

    def test_reward_product_combo_raises(self):
        """A free-product reward can't target a combo product."""
        combo_item_product = self.env["product.product"].create({"name": "Combo Item"})
        combo = self.env["product.combo"].create(
            {
                "name": "Test Combo",
                "combo_item_ids": [
                    Command.create({"product_id": combo_item_product.id})
                ],
            }
        )
        combo_template = self.env["product.template"].create(
            {
                "name": "Combo Product",
                "type": "combo",
                "combo_ids": [Command.set([combo.id])],
            }
        )

        with self.assertRaises(ValidationError):
            self.env["loyalty.program"].create(
                {
                    "name": "Combo Program",
                    "reward_ids": [
                        Command.create(
                            {
                                "reward_type": "product",
                                "reward_product_id": (
                                    combo_template.product_variant_id.id
                                ),
                            }
                        )
                    ],
                }
            )
