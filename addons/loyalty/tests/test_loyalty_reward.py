# Part of Odoo. See LICENSE file for full copyright and licensing details.

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
