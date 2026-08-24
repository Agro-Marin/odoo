from datetime import timedelta

from odoo.fields import Command, Date
from odoo.tests.common import tagged

from odoo.addons.sale_loyalty.tests.common import TestSaleCouponCommon


@tagged("-at_install", "post_install")
class TestUnlinkReward(TestSaleCouponCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The reward is declared with the program: a program created with a
        # `program_type` and no `reward_ids` is given the one its type implies, so
        # adding a second one afterwards left the order claiming whichever it liked.
        cls.promotion_program = cls.env["loyalty.program"].create(
            {
                "name": "Buy A + 1 B, 1 B are free",
                "program_type": "promotion",
                "applies_on": "current",
                "company_id": cls.env.company.id,
                "trigger": "auto",
                "rule_ids": [
                    Command.create(
                        {
                            "product_ids": cls.product_A,
                            "reward_point_amount": 1,
                            "reward_point_mode": "order",
                            "minimum_qty": 1,
                        }
                    )
                ],
                "reward_ids": [Command.create({"reward_type": "discount"})],
            }
        )
        cls.reward = cls.promotion_program.reward_ids.ensure_one()

    def test_sale_unlink_reward(self):
        order = self.empty_order
        order.write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_A.id,
                            "name": "Ordinary Product A",
                            "product_qty": 1.0,
                        }
                    ),
                    Command.create(
                        {
                            "product_id": self.product_B.id,
                            "name": "2 Product B",
                            "product_qty": 1.0,
                        }
                    ),
                ]
            }
        )
        order._update_programs_and_rewards()
        self._claim_reward(order, self.promotion_program)
        self.reward.unlink()

        # Check that the reward is archived and not deleted
        self.assertTrue(self.reward.exists())
        self.assertFalse(self.reward.active)

    def test_unlink_expired_coupon_line(self):
        """Ensure that lines linked to expired coupons get unlinked from the order."""
        order = self.empty_order
        order.line_ids = [Command.create({"product_id": self.product_A.id})]
        coupon_program = self.code_promotion_program
        self.env["loyalty.generate.wizard"].with_context(
            active_id=coupon_program.id
        ).create(
            {
                "coupon_qty": 1,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = coupon_program.coupon_ids
        self._apply_promo_code(order, coupon.code)
        self.assertTrue(order.line_ids.coupon_id)
        coupon.expiration_date = Date.today() - timedelta(days=1)
        order._update_programs_and_rewards()
        self.assertFalse(order.line_ids.coupon_id)
