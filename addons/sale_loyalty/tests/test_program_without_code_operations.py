from odoo.addons.sale_loyalty.tests.common import TestSaleCouponCommon


class TestProgramWithoutCodeOperations(TestSaleCouponCommon):
    def test_immediate_program_basic_operation(self):

        self.immediate_promotion_program.rule_ids.write({"minimum_qty": 2.0})
        order = self.empty_order
        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_A.id,
                            "name": "1 Product A",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        order._update_programs_and_rewards()
        self._claim_reward(order, self.immediate_promotion_program)
        self.assertEqual(
            len(order.line_ids.ids),
            1,
            "The promo offer shouldn't have been applied as the product B isn't in the order",
        )

        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_B.id,
                            "name": "2 Product B",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        order._update_programs_and_rewards()
        self._claim_reward(order, self.immediate_promotion_program)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "The promo offer shouldn't have been applied as 2 product A aren't in the order",
        )

        order.write({"line_ids": [(1, order.line_ids[0].id, {"product_qty": 2.0})]})
        order._update_programs_and_rewards()
        self._claim_reward(order, self.immediate_promotion_program)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "The promo offer should have been applied, the discount is not created",
        )

        order.write({"line_ids": [(1, order.line_ids[0].id, {"product_qty": 1.0})]})
        order._update_programs_and_rewards()
        self._claim_reward(order, self.immediate_promotion_program)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "The promo reward should have been removed as the rules are not matched anymore",
        )
        self.assertEqual(
            order.line_ids[0].product_id.id,
            self.product_A.id,
            "The wrong line has been removed",
        )
        self.assertEqual(
            order.line_ids[1].product_id.id,
            self.product_B.id,
            "The wrong line has been removed",
        )

        order.write(
            {
                "line_ids": [
                    (1, order.line_ids[0].id, {"product_qty": 2.0}),
                    (2, order.line_ids[0].id, False),
                ]
            }
        )
        order._update_programs_and_rewards()
        self._claim_reward(order, self.immediate_promotion_program)
        self.assertEqual(
            len(order.line_ids.ids),
            1,
            "The promo reward should have been removed as the rules are not matched anymore",
        )
        self.assertEqual(
            order.line_ids.product_id.id,
            self.product_B.id,
            "The wrong line has been removed",
        )
