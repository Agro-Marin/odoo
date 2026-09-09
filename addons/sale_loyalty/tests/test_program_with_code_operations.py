from odoo.exceptions import ValidationError
from odoo.fields import Command

from odoo.addons.sale_loyalty.tests.common import TestSaleCouponCommon


class TestProgramWithCodeOperations(TestSaleCouponCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.discount_with_multi_rewards = cls.env["loyalty.program"].create(
            {
                "name": "Loyalty program with multiple discount rewards",
                "program_type": "coupons",
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 20,
                        }
                    ),
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 5,
                        }
                    ),
                ],
            }
        )

    def test_program_usability(self):
        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.code_promotion_program.id
        ).create(
            {
                "mode": "selected",
            }
        ).generate_coupons()
        self.assertEqual(
            len(self.code_promotion_program.coupon_ids),
            len(self.env["res.partner"].search([])),
            "It should have generated a coupon for every partner",
        )

    def test_program_basic_operation_coupon_code(self):

        self.immediate_promotion_program.active = False
        self.code_promotion_program.reward_ids.reward_type = "discount"
        self.code_promotion_program.reward_ids.discount = 10

        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.code_promotion_program.id
        ).create(
            {
                "mode": "selected",
                "customer_ids": self.partner,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = self.code_promotion_program.coupon_ids

        wrong_partner_order = self.env["sale.order"].create(
            {
                "partner_id": self.env["res.partner"].create({"name": "My Partner"}).id,
            }
        )
        with self.assertRaises(ValidationError):
            self._apply_promo_code(wrong_partner_order, coupon.code)

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
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(len(order.line_ids.ids), 2)

        order.write({"line_ids": [(2, order.line_ids[0].id, False)]})
        order._update_programs_and_rewards()
        self.assertEqual(len(order.line_ids.ids), 0)

    def test_program_coupon_double_consuming(self):

        self.immediate_promotion_program.active = False
        self.code_promotion_program.applies_on = "future"
        self.code_promotion_program.reward_ids.reward_type = "discount"
        self.code_promotion_program.reward_ids.discount = 10

        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.code_promotion_program.id
        ).create(
            {
                "coupon_qty": 1,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = self.code_promotion_program.coupon_ids

        sale_order_a = self.empty_order.copy()
        sale_order_b = self.empty_order.copy()

        sale_order_a.write(
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
        self._apply_promo_code(sale_order_a, coupon.code)
        self.assertEqual(len(sale_order_a.line_ids.ids), 2)

        sale_order_a._action_cancel()

        sale_order_b.write(
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
        self._apply_promo_code(sale_order_b, coupon.code)
        self.assertEqual(len(sale_order_b.line_ids.ids), 2)

        sale_order_b.action_confirm()

        sale_order_a.action_draft()
        sale_order_a.action_confirm()
        self.assertEqual(len(sale_order_a.line_ids.ids), 1)

    def test_coupon_code_with_pricelist(self):

        self.code_promotion_program_with_discount.applies_on = "future"
        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.code_promotion_program_with_discount.id
        ).create(
            {
                "coupon_qty": 1,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = self.code_promotion_program_with_discount.coupon_ids

        first_pricelist = self.env["product.pricelist"].create(
            {
                "name": "First pricelist",
                "item_ids": [
                    (
                        0,
                        0,
                        {
                            "compute_price": "percentage",
                            "base": "list_price",
                            "percent_price": 10,
                            "applied_on": "3_global",
                            "name": "First discount",
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        order.pricelist_id = first_pricelist
        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_C.id,
                            "name": "1 Product C",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(len(order.line_ids.ids), 2)
        self.assertEqual(
            order.amount_total,
            81,
            "SO total should be 81: (10% of 100 with pricelist) + 10% of 90 with coupon code",
        )

    def test_on_next_order_reward_promotion_program(self):

        self.immediate_promotion_program.write(
            {
                "applies_on": "future",
                "trigger": "with_code",
            }
        )
        self.immediate_promotion_program.rule_ids.write(
            {
                "mode": "with_code",
                "code": "free_B_on_next_order",
            }
        )
        self.p1 = self.env["loyalty.program"].create(
            {
                "name": "Code for 10% on next order",
                "program_type": "promotion",
                "applies_on": "future",
                "trigger": "auto",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                        },
                    )
                ],
            }
        )
        order = self.empty_order.copy()
        self.third_product = self.env["product.product"].create(
            {"name": "Thrid Product", "list_price": 5, "sale_ok": True}
        )
        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.third_product.id,
                            "name": "1 Third Product",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        order._update_programs_and_rewards()
        self.assertEqual(
            len(self.p1.coupon_ids.ids),
            1,
            "You should get a coupon for you next order that will offer 10% discount",
        )
        with self.assertRaises(ValidationError):
            self._apply_promo_code(order, "free_B_on_next_order")
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
        self._apply_promo_code(order, "free_B_on_next_order", no_reward_fail=False)
        self.assertEqual(
            len(order._get_reward_coupons()),
            2,
            "You should get a second coupon for your next order that will offer a free Product B",
        )
        order.action_confirm()
        order_bis = self.empty_order

        order_bis.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_B.id,
                            "name": "1 Product B",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        self._apply_promo_code(order_bis, order._get_reward_coupons()[1].code)
        self.assertEqual(len(order_bis.line_ids), 2, "You should get a free Product B")
        self._apply_promo_code(order_bis, order._get_reward_coupons()[0].code)
        self.assertEqual(
            len(order_bis.line_ids), 3, "You should get a 10% discount line"
        )
        self.assertAlmostEqual(
            order_bis.amount_total,
            order_bis.line_ids[0].price_total * 0.9,
            2,
            "SO total should be null: (Paid product - Free product = 0) + 10% of nothing",
        )

    def test_on_next_order_reward_promotion_program_with_requirements(self):
        self.immediate_promotion_program.write(
            {
                "applies_on": "future",
                "trigger": "with_code",
            }
        )
        self.immediate_promotion_program.rule_ids.write(
            {
                "minimum_amount": 700,
                "minimum_amount_tax_mode": "excl",
                "mode": "with_code",
                "code": "free_B_on_next_order",
            }
        )
        order = self.empty_order.copy()
        self.product_A.lst_price = 700
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
        self._apply_promo_code(order, "free_B_on_next_order", no_reward_fail=False)
        self.assertEqual(
            len(self.immediate_promotion_program.coupon_ids.ids),
            1,
            "You should get a coupon for you next order that will offer a free product B",
        )
        order_bis = self.empty_order
        order_bis.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_B.id,
                            "name": "1 Product B",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        with self.assertRaises(ValidationError):
            self._apply_promo_code(order_bis, order._get_reward_coupons()[0].code)
        order.action_confirm()
        self._apply_promo_code(
            order_bis, order._get_reward_coupons()[0].code, no_reward_fail=False
        )
        self.assertEqual(
            len(order_bis.line_ids),
            2,
            "You should get 1 regular product_B and 1 free product_B",
        )
        order_bis._update_programs_and_rewards()
        self.assertEqual(
            len(order_bis.line_ids),
            2,
            "Free product from a coupon generated from a promotion program on next order should not dissapear",
        )

    def test_partner_assigned_to_next_order_coupon(self):
        loyalty_program = self.env["loyalty.program"].create(
            {
                "name": "10% Discount on Next Order",
                "program_type": "next_order_coupons",
                "applies_on": "future",
                "trigger": "auto",
                "rule_ids": [Command.create({})],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                        }
                    )
                ],
            }
        )
        order = self.empty_order
        order.write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_A.id,
                            "name": "1 Product A",
                            "product_qty": 1.0,
                        }
                    )
                ]
            }
        )
        generated_coupons = order._try_apply_program(loyalty_program).get("coupon")
        self.assertTrue(generated_coupons, "A coupon should have been generated")
        self.assertEqual(
            generated_coupons.partner_id,
            order.partner_id,
            "The partner should be set on the coupon with program type 'next_order_coupons'",
        )

    def test_public_partner_updated_in_next_order_coupon(self):
        loyalty_program = self.env["loyalty.program"].create(
            {
                "name": "10% Discount on Next Order",
                "program_type": "next_order_coupons",
                "applies_on": "future",
                "trigger": "auto",
                "rule_ids": [Command.create({})],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                        }
                    )
                ],
            }
        )
        order = self.empty_order
        order.write(
            {
                "partner_id": self.env.ref("base.public_partner").id,
                "line_ids": [Command.create({"product_id": self.product_A.id})],
            }
        )
        generated_coupons = order._try_apply_program(loyalty_program).get("coupon")
        self.assertTrue(generated_coupons, "A coupon should have been generated")
        self.assertEqual(
            generated_coupons.partner_id,
            order.partner_id,
            "The partner should be set on the coupon with program type 'next_order_coupons'",
        )
        self.assertTrue(generated_coupons.partner_id.is_public)

        order.partner_id = self.partner
        order._update_programs_and_rewards()
        self.assertEqual(
            generated_coupons.partner_id,
            self.partner,
            "The coupon's partner_id should be updated if it was created for a Public User",
        )

    def test_change_reward_on_confirmed_order(self):
        program = self.code_promotion_program_with_discount
        program.update(
            {
                "rule_ids": [Command.clear()],
                "reward_ids": [
                    Command.create(
                        {
                            "discount": 50,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                            "required_points": 5,
                        }
                    )
                ],
            }
        )
        discount10, discount50 = program.reward_ids

        self.env["loyalty.generate.wizard"].with_context(active_id=program.id).create(
            {
                "coupon_qty": 1,
                "points_granted": 10,
            }
        ).generate_coupons()
        coupon = program.coupon_ids

        order = self.empty_order
        order.line_ids = [Command.create({"product_id": self.product_C.id})]
        order.action_confirm()

        order._apply_program_reward(discount10, coupon)
        reward_line = order.line_ids.filtered("is_reward_line")
        self.assertEqual(order.amount_total, 90, "10% discount should be applied")
        self.assertEqual(coupon.points, 9, "10% discount reward should use 1 point")

        order._apply_program_reward(discount50, coupon)
        self.assertIn(reward_line, order.line_ids, "Reward line should be re-used")
        self.assertEqual(order.amount_total, 50, "50% discount should be applied")
        self.assertEqual(coupon.points, 5, "50% discount reward should use 5 points")

    def test_edit_and_reapply_promotion_program(self):

        self.immediate_promotion_program.active = False
        self.p1 = self.env["loyalty.program"].create(
            {
                "name": "Promo fixed amount",
                "trigger": "auto",
                "program_type": "promotion",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "per_point",
                            "discount_applicability": "order",
                        },
                    )
                ],
            }
        )
        order = self.empty_order.copy()
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
        self._claim_reward(order, self.p1)
        self.assertEqual(len(order.line_ids), 2, "You should get a discount line")
        self.p1.write(
            {
                "trigger": "with_code",
            }
        )
        self.p1.rule_ids.write(
            {
                "mode": "with_code",
                "code": "test",
            }
        )
        order._update_programs_and_rewards()
        self.assertEqual(len(order.line_ids), 1, "You loose a discount line")
        self._apply_promo_code(order, "test")
        self.assertEqual(len(order.line_ids), 2, "You should get a discount line")

    def test_reapply_multiple_global_rewards_when_new_discount_greater(self):
        self.code_promotion_program_with_discount.rule_ids.unlink()
        coupon_1 = self._generate_coupons(self.code_promotion_program_with_discount)
        coupon_2 = self._generate_coupons(self.discount_with_multi_rewards)

        order = self.empty_order
        self.assertEqual(order.amount_total, 0.0)
        order.write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_A.id,
                            "name": "1 Product A",
                            "product_qty": 1.0,
                        }
                    ),
                    Command.create(
                        {
                            "product_id": self.product_B.id,
                            "name": "1 Product B",
                            "product_qty": 1.0,
                        }
                    ),
                ]
            }
        )

        self.assertEqual(len(order.line_ids.ids), 2)
        self.assertEqual(order.line_ids[0].price_unit, 100.0)
        self.assertEqual(order.line_ids[1].price_unit, 5.0)
        expected_total = order.amount_total * 0.80

        self._apply_promo_code(order, coupon_1.code)
        self.assertEqual(len(order.line_ids.ids), 3)
        msg = "The discount line should be the 10% discount on the sale order total."
        self.assertEqual(order.line_ids[2].price_unit, -10.5, msg=msg)

        self._apply_promo_code(order, coupon_2.code)
        self.assertEqual(len(order.line_ids.ids), 3)
        msg = "The discount line should be the 20% discount on the sale order total."
        self.assertEqual(order.line_ids[2].price_unit, -21.0, msg=msg)
        msg = "Order total should reflect the 20% discount"
        self.assertAlmostEqual(order.amount_total, expected_total, msg=msg)

    def test_reapply_multiple_higher_global_rewards_lets_choose_best(self):
        self.code_promotion_program_with_discount.rule_ids.unlink()
        coupon_1 = self._generate_coupons(self.code_promotion_program_with_discount)
        self.discount_with_multi_rewards.reward_ids[1].discount = 15
        coupon_2 = self._generate_coupons(self.discount_with_multi_rewards)

        order = self.empty_order
        self.assertEqual(order.amount_total, 0.0)
        order.write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_A.id,
                            "name": "1 Product A",
                            "product_qty": 1.0,
                        }
                    )
                ]
            }
        )

        self.assertEqual(len(order.line_ids.ids), 1)
        self.assertEqual(order.line_ids[0].price_unit, 100.0)
        expected_total = order.amount_total * 0.80

        self._apply_promo_code(order, coupon_1.code)
        self.assertEqual(len(order.line_ids.ids), 2)
        msg = "The discount line should be the 10% discount on the sale order total."
        self.assertEqual(order.line_ids[1].price_unit, -10.0, msg=msg)

        rewards = self._apply_promo_code(order, coupon_2.code)
        self.assertEqual(len(rewards), 2)

        chosen_reward = rewards.filtered(lambda r: r.discount == 20)
        order._apply_program_reward(chosen_reward, coupon_2)
        self.assertEqual(len(order.line_ids), 2)
        msg = "The discount line should be the 20% discount on the sale order total."
        self.assertEqual(order.line_ids[1].price_unit, -20.0, msg=msg)
        msg = "Order total should reflect the 20% discount"
        self.assertAlmostEqual(order.amount_total, expected_total, msg=msg)

    def test_reapplying_new_multiple_lower_global_rewards_discount_raise_validation(
        self,
    ):
        self.code_promotion_program_with_discount.rule_ids.unlink()
        coupon_1 = self._generate_coupons(self.code_promotion_program_with_discount)
        self.discount_with_multi_rewards.reward_ids[0].discount = 7
        coupon_2 = self._generate_coupons(self.discount_with_multi_rewards)

        order = self.empty_order
        self.assertEqual(order.amount_total, 0.0)
        order.write(
            {
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_A.id,
                            "name": "1 Product A",
                            "product_qty": 1.0,
                        }
                    )
                ]
            }
        )

        self.assertEqual(len(order.line_ids.ids), 1)
        self.assertEqual(order.line_ids[0].price_unit, 100.0)

        self._apply_promo_code(order, coupon_1.code)
        msg = "The discount line should be the 10% discount on the sale order total."
        self.assertEqual(order.line_ids[1].price_unit, -10.0, msg=msg)
        self.assertEqual(len(order.line_ids.ids), 2)

        msg = (
            "The new coupon discount should be greater than the applied coupon discount"
        )
        with self.assertRaises(ValidationError, msg=msg):
            self._apply_promo_code(order, coupon_2.code)
