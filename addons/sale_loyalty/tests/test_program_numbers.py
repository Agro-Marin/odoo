from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.libs.numbers import float_compare
from odoo.tests import tagged

from odoo.addons.sale_loyalty.tests.common import TestSaleCouponNumbersCommon


@tagged("post_install", "-at_install")
class TestSaleCouponProgramNumbers(TestSaleCouponNumbersCommon):
    def test_program_numbers_free_and_paid_product_qty(self):
        order = self.empty_order
        sol1 = self._add_line(order, self.largeCabinet, 3.0, name="Large Cabinet")

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "We should have 2 lines as we now have one 'Free Large Cabinet' line as we bought 3 of them",
        )

        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "We should have 3 lines as we should have a new line for promo code reduction",
        )
        self.assertEqual(
            order.amount_total,
            864,
            "Only paid product should have their price discounted",
        )
        order.line_ids.filtered(lambda x: "Discount" in x.name).unlink()
        order._remove_program_from_points(self.p1)

        sol1.product_qty = 2
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 1, "Free Large Cabinet should have been removed"
        )

        sol1.product_qty = 75
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            sum(
                order.line_ids.filtered(lambda x: x.is_reward_line).mapped(
                    "product_qty"
                )
            ),
            25,
            "We should have 25 Free Large Cabinet",
        )
        sol1.product_qty = 6
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            sum(
                order.line_ids.filtered(lambda x: x.is_reward_line).mapped(
                    "product_qty"
                )
            ),
            2,
            "We should have 2 Free Large Cabinet",
        )

    def test_program_numbers_check_eligibility(self):

        order = self.empty_order
        sol1 = self._add_line(order, self.drawerBlack, 3.0, name="drawer black")
        sol2 = self._add_line(order, self.largeMeetingTable, 1.0)
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "We should have a 'Free Large Meeting Table' promotion line",
        )
        self.assertEqual(
            sum(
                order.line_ids.filtered(lambda x: x.is_reward_line).mapped(
                    "product_qty"
                )
            ),
            1,
            "We should receive one and only one free Large Meeting Table",
        )

        sol1.product_qty = 1
        sol2.product_qty = 2
        self.p1.rule_ids.minimum_amount = 5000
        self._auto_rewards(order, self.all_programs)
        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(
            len(order.line_ids.ids),
            4,
            "We should have 4 lines as we should have a new line for promo code reduction",
        )
        self.assertAlmostEqual(
            order.amount_total,
            72022.5,
            msg="Free product value should not be subtracted twice from the discountable amount",
        )
        self.assertAlmostEqual(
            order.amount_untaxed,
            72022.5,
            msg="Free product value should not be subtracted twice from the discountable amount",
        )

        self.env["sale.order.line"].create(
            {
                "product_id": self.largeCabinet.id,
                "name": "Large Cabinet",
                "product_qty": 4.0,
                "order_id": order.id,
            }
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            6,
            "We should have 2 more lines as we now have one 'Free Large Cabinet' line since we bought 4 of them",
        )

    def test_program_numbers_taxes_and_rules(self):
        percent_tax = self.env["account.tax"].create(
            {
                "name": "15% Tax",
                "amount_type": "percent",
                "amount": 15,
                "price_include_override": "tax_included",
            }
        )
        p_specific_product = self.env["loyalty.program"].create(
            {
                "name": "20% reduction on Large Cabinet in cart",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "minimum_amount_tax_mode": "excl",
                            "minimum_amount": 320.00,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 20,
                            "discount_mode": "percent",
                            "discount_applicability": "specific",
                            "discount_product_ids": self.largeCabinet,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= p_specific_product
        order = self.empty_order
        self.largeCabinet.taxes_id = percent_tax
        sol1 = self._add_line(order, self.largeCabinet, 1.0, name="Large Cabinet")

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            1,
            "We should not get the reduction line since we dont have 320$ tax excluded (cabinet is 320$ tax included)",
        )
        sol1.tax_ids.price_include_override = "tax_excluded"
        sol1._compute_tax_ids()
        self.env.flush_all()
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "We should now get the reduction line since we have 320$ tax included (cabinet is 320$ tax included)",
        )
        self.assertAlmostEqual(
            order.amount_total,
            294.4,
            2,
            "Check discount has been applied correctly (eg: on taxes aswell)",
        )

        p_specific_product.write({"trigger": "with_code"})
        p_specific_product.rule_ids.write({"mode": "with_code", "code": "20pc"})
        order.line_ids.filtered(lambda l: l.is_reward_line).unlink()
        order._remove_program_from_points(p_specific_product)
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            1,
            "Reduction should be removed since we deleted it and it is now a promo code usage, it shouldn't be automatically reapplied",
        )

        self._apply_promo_code(order, "20pc")
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "We should now get the reduction line since we have 320$ tax included (cabinet is 320$ tax included)",
        )

        self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "Drawer Black",
                "product_qty": 10.0,
                "order_id": order.id,
            }
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total, 544.4, "We should only get reduction on cabinet"
        )
        sol1.product_qty = 8
        self._auto_rewards(order, self.all_programs)
        self.assertAlmostEqual(
            order.amount_total,
            2605.20,
            2,
            "Changing cabinet quantity should change discount amount correctly",
        )

        p_specific_product.reward_ids.discount_max_amount = 200
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            2994.0,
            "The discount should be limited to $200 tax included",
        )
        self.assertEqual(
            order.amount_untaxed,
            2636.09,
            "The discount should be limited to $200 tax included (2)",
        )

    def test_program_numbers_one_discount_line_per_tax(self):
        order = self.empty_order
        self.env["ir.config_parameter"].set_param(
            "loyalty.compute_all_discount_product_ids", "enabled"
        )
        self.tax_50pc_excl = self.env["account.tax"].create(
            {
                "name": "50% Tax excl",
                "amount_type": "percent",
                "amount": 50,
            }
        )
        self.tax_35pc_incl = self.env["account.tax"].create(
            {
                "name": "35% Tax incl",
                "amount_type": "percent",
                "amount": 35,
                "price_include_override": "tax_included",
            }
        )

        (
            self.product_A
            + self.largeCabinet
            + self.conferenceChair
            + self.pedalBin
            + self.drawerBlack
        ).write({"list_price": 100})
        (self.largeCabinet + self.drawerBlack).write(
            {"taxes_id": [(4, self.tax_15pc_excl.id, False)]}
        )
        self.conferenceChair.taxes_id = self.tax_10pc_incl
        self.pedalBin.taxes_id = None
        self.product_A.taxes_id = self.tax_35pc_incl + self.tax_50pc_excl

        self.env["sale.order.line"].create(
            {
                "product_id": self.largeCabinet.id,
                "name": "Large Cabinet",
                "product_qty": 4.0,
                "order_id": order.id,
            }
        )
        sol2 = self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conference Chair",
                "product_qty": 3.0,
                "order_id": order.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "product_id": self.pedalBin.id,
                "name": "Pedal Bin",
                "product_qty": 5.0,
                "order_id": order.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "product_id": self.product_A.id,
                "name": "product A with multiple taxes",
                "product_qty": 3.0,
                "order_id": order.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "Drawer Black",
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )

        self.immediate_promotion_program.active = False
        self.p2.active = False
        self.p3.active = False

        self.p_large_cabinet = self.env["loyalty.program"].create(
            {
                "name": "Buy 1 large cabinet, get 3/4 for free",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.largeCabinet,
                            "reward_point_mode": "unit",
                            "minimum_qty": 1,
                            "reward_point_amount": 0.752,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.largeCabinet.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.p_conference_chair = self.env["loyalty.program"].create(
            {
                "name": "Buy 1 chair, get one for free",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.conferenceChair,
                            "reward_point_mode": "unit",
                            "minimum_qty": 1,
                            "reward_point_amount": 0.4,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.conferenceChair.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.p_pedal_bin = self.env["loyalty.program"].create(
            {
                "name": "Buy 1 bin, get one for free",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.pedalBin,
                            "reward_point_mode": "unit",
                            "minimum_qty": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.pedalBin.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= (
            self.p_large_cabinet | self.p_conference_chair | self.p_pedal_bin
        )

        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1901.11,
                    "amount_untaxed": 1594.95,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            5,
            "The order without any programs should have 5 lines",
        )

        self._auto_rewards(order, self.all_programs)

        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1901.11,
                    "amount_untaxed": 1594.95,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            8,
            "Order should contains 5 regular product lines and 3 free product lines",
        )

        self._apply_promo_code(order, "test_10pc")

        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1711.0,
                    "amount_untaxed": 1435.45,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            12,
            "Order should contains 5 regular product lines, 3 free product lines and 4 discount lines (one for every tax)",
        )

        order.line_ids._compute_tax_ids()
        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1711.0,
                    "amount_untaxed": 1435.45,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            12,
            "Recomputing tax on sale order lines should not change number of order line",
        )
        self._auto_rewards(order, self.all_programs)
        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1711.0,
                    "amount_untaxed": 1435.45,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            12,
            "Recomputing tax on sale order lines should not change number of order line",
        )

        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "20% reduction on Large Cabinet in cart",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 20,
                            "discount_applicability": "specific",
                            "discount_product_ids": self.largeCabinet,
                            "required_points": 1,
                            "clear_wallet": 1,
                        },
                    )
                ],
            }
        )
        self._auto_rewards(order, self.all_programs)

        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1628.2,
                    "amount_untaxed": 1363.45,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            13,
            "Order should have a new discount line for 20% on Large Cabinet",
        )

        order.line_ids.filtered(lambda l: "10%" in l.name)[0].unlink()
        order._remove_program_from_points(self.p1)
        self.assertEqual(
            len(order.line_ids.ids),
            9,
            "All of the 10% discount line per tax should be removed",
        )

        self._apply_promo_code(order, "test_10pc")
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 13, "The 10% discount line should be back"
        )

        self.p_conference_chair.rule_ids.reward_point_amount = 0.752
        sol2.product_qty = 4
        self._auto_rewards(order, self.all_programs)

        self.assertEqual(
            order.amount_untaxed,
            1445.27,
            "The order should have one more paid Conference Chair with 10% incl tax and discounted by 10%",
        )

        sol2.unlink()
        self._auto_rewards(order, self.all_programs)

        self.assertRecordValues(
            order,
            [
                {
                    "amount_total": 1358.2,
                    "amount_untaxed": 1118.0,
                }
            ],
        )
        self.assertEqual(
            len(order.line_ids.ids),
            10,
            "Order should contains 10 lines: 4 products lines, 2 free products lines and 4 discount lines",
        )

    def test_program_numbers_extras(self):
        p1_copy = self.p1.copy(
            {
                "trigger": "auto",
                "name": "Auto applied 10% global discount",
                "rule_ids": [(0, 0, {})],
            }
        )
        self.all_programs |= p1_copy
        order = self.empty_order
        self._add_line(order, self.largeCabinet, 1.0, name="Large Cabinet")
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "We should get 1 Large Cabinet line and 1 10% auto applied global discount line",
        )
        self.assertEqual(order.amount_total, 288, "320$ - 10%")
        with self.assertRaises(ValidationError):
            self._apply_promo_code(order, "test_10pc")

    def test_program_fixed_price(self):
        order = self.empty_order
        self.p3.active = False
        fixed_amount_program = self.env["loyalty.program"].create(
            {
                "name": "$249 discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "reward_point_amount": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 249,
                            "discount_mode": "per_point",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= fixed_amount_program
        self.tax_0pc_excl = self.env["account.tax"].create(
            {
                "name": "0% Tax excl",
                "amount_type": "percent",
                "amount": 0,
            }
        )
        fixed_amount_program.reward_ids.discount_line_product_id.write(
            {"taxes_id": [(4, self.tax_0pc_excl.id, False)]}
        )
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "Drawer Black",
                "product_qty": 1.0,
                "order_id": order.id,
                "tax_ids": [(4, self.tax_0pc_excl.id)],
            }
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            0,
            "Total should be null. The fixed amount discount is higher than the SO total, it should be reduced to the SO total",
        )
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "There should be the product line and the reward line",
        )
        sol1.product_qty = 17
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total, 176, "Fixed amount discount should be totally deduced"
        )
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "Number of lines should be unchanged as we just recompute the reward line",
        )
        fixed_amount_program.write({"active": False})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            1,
            "Archiving the program should remove the program reward line",
        )

    def test_program_next_order(self):
        order = self.empty_order
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "Free Pedal Bin if at least 1 article",
                "trigger": "auto",
                "applies_on": "future",
                "program_type": "promotion",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "minimum_qty": 2,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.pedalBin.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.largeCabinet.id,
                "name": "Large Cabinet",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 1, "Nothing should be added to the cart"
        )
        self.assertEqual(
            len(order._get_reward_coupons()),
            0,
            "No coupon should have been generated yet",
        )

        sol1.product_qty = 2
        self._auto_rewards(order, self.all_programs)
        generated_coupon = order._get_reward_coupons()
        self.assertEqual(
            len(order.line_ids.ids), 1, "Nothing should be added to the cart (2)"
        )
        self.assertEqual(
            len(generated_coupon), 1, "A coupon should have been generated"
        )
        self.assertEqual(
            generated_coupon.points,
            0,
            "The coupon should not have it's points already.",
        )

        sol1.product_qty = 1
        self._auto_rewards(order, self.all_programs)
        generated_coupon = order._get_reward_coupons()
        self.assertEqual(
            len(order.line_ids.ids), 1, "Nothing should be added to the cart (3)"
        )
        self.assertEqual(
            len(generated_coupon),
            0,
            "No more coupon should have been generated and the existing one should not have been deleted",
        )

        sol1.product_qty = 2
        self._auto_rewards(order, self.all_programs)
        generated_coupon = order._get_reward_coupons()
        self.assertEqual(
            len(generated_coupon),
            1,
            "We should still have only 1 coupon as we now benefit again from the program but no need to create a new one (see next assert)",
        )
        self.assertEqual(
            generated_coupon.points,
            0,
            "The coupon should not have it's points already.",
        )
        self.assertFalse(
            order._get_claimable_rewards(), "No rewards should be claimable"
        )

        order.action_confirm()
        self.assertEqual(
            generated_coupon.points,
            1,
            "The coupon should have 1 point after confirmation",
        )
        self.assertFalse(
            order._get_claimable_rewards(),
            "Next-order coupon rewards shouldn't be claimable on current order",
        )

    def test_coupon_rule_minimum_amount(self):
        order = self.empty_order
        self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conference Chair",
                "product_qty": 10.0,
                "order_id": order.id,
            }
        )
        self.assertEqual(order.amount_total, 165.0, "The order amount is not correct")
        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.discount_coupon_program.id
        ).create(
            {
                "coupon_qty": 1,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = self.discount_coupon_program.coupon_ids[0]
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(
            order.amount_total, 65.0, "The coupon should be correctly applied"
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total, 65.0, "The coupon should not be removed from the order"
        )

    def test_coupon_and_program_discount_fixed_amount(self):
        order = self.empty_order
        orderline = self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conference Chair",
                "product_qty": 10.0,
                "order_id": order.id,
            }
        )
        self.assertEqual(order.amount_total, 165.0, "The order amount is not correct")

        self.env["loyalty.program"].create(
            {
                "name": "$100 promotion program",
                "program_type": "promotion",
                "trigger": "with_code",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "mode": "with_code",
                            "code": "testpromo",
                            "minimum_amount": 100,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 100,
                            "discount_mode": "per_point",
                            "discount_applicability": "order",
                        },
                    )
                ],
            }
        )

        self._apply_promo_code(order, "testpromo")
        self.assertEqual(
            order.amount_total,
            65.0,
            "The promotion program should be correctly applied",
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            65.0,
            "The promotion program should not be removed after recomputation",
        )

        self.env["loyalty.generate.wizard"].with_context(
            active_id=self.discount_coupon_program.id
        ).create(
            {
                "coupon_qty": 1,
                "points_granted": 1,
            }
        ).generate_coupons()
        coupon = self.discount_coupon_program.coupon_ids[0]
        with self.assertRaises(ValidationError):
            self._apply_promo_code(order, coupon.code)
        orderline.write({"product_qty": 15})
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(
            order.amount_total,
            47.5,
            "The promotion program should now be correctly applied",
        )

        orderline.write({"product_qty": 5})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            82.5,
            "The promotion programs should have been removed from the order to avoid negative amount",
        )

    def test_coupon_and_coupon_discount_fixed_amount_tax_excl(self):

        self.immediate_promotion_program.active = False
        coupon_program = self.env["loyalty.program"].create(
            {
                "name": "$288.5 coupon",
                "program_type": "coupons",
                "trigger": "with_code",
                "applies_on": "current",
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "per_point",
                            "discount": 288.5,
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        self.env["sale.order.line"].create(
            [
                {
                    "product_id": self.conferenceChair.id,
                    "name": "Conference Chair",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, (self.tax_15pc_excl.id,))],
                },
                {
                    "product_id": self.pedalBin.id,
                    "name": "Computer Case",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, [])],
                },
                {
                    "product_id": self.product_A.id,
                    "name": "Computer Case",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, [])],
                },
            ]
        )

        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(
            order.amount_total,
            283.5,
            "The promotion program should be correctly applied",
        )

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
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_tax, 0.0)
        self.assertEqual(
            order.amount_untaxed, 0.0, "The untaxed amount should not go below 0"
        )
        self.assertEqual(
            order.amount_total,
            0.0,
            "The promotion program should not make the order total go below 0",
        )

        order.line_ids[3:].unlink()
        order._remove_program_from_points(coupon_program)
        order._remove_program_from_points(self.p1)

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids), 3, "The promotion program should be removed"
        )
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(
            order.amount_total,
            26.5,
            "The promotion program should be correctly applied",
        )
        self._auto_rewards(order, self.all_programs)
        self._apply_promo_code(order, "test_10pc")
        self._auto_rewards(order, self.all_programs)
        self.assertAlmostEqual(order.amount_tax, 1.14, 2)
        self.assertEqual(order.amount_untaxed, 22.71)
        self.assertEqual(
            order.amount_total,
            23.85,
            "The promotion program should not make the order total go below 0be altered after recomputation",
        )
        self._auto_rewards(order, self.all_programs)
        self.assertAlmostEqual(order.amount_tax, 1.14, 2)
        self.assertEqual(order.amount_untaxed, 22.71)
        self.assertEqual(
            order.amount_total,
            23.85,
            "The promotion program should not make the order total go below 0be altered after recomputation",
        )

    def test_coupon_and_coupon_discount_fixed_amount_tax_incl(self):

        self.immediate_promotion_program.active = False
        coupon_program = self.env["loyalty.program"].create(
            {
                "name": "$290 coupon",
                "program_type": "coupons",
                "trigger": "with_code",
                "applies_on": "current",
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "per_point",
                            "discount": 290,
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        self.env["sale.order.line"].create(
            [
                {
                    "product_id": self.conferenceChair.id,
                    "name": "Conference Chair",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, (self.tax_10pc_incl.id,))],
                },
                {
                    "product_id": self.pedalBin.id,
                    "name": "Computer Case",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, [])],
                },
                {
                    "product_id": self.product_A.id,
                    "name": "Computer Case",
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                    "order_id": order.id,
                    "tax_ids": [(6, 0, [])],
                },
            ]
        )

        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(
            order.amount_total,
            270.0,
            "The promotion program should be correctly applied",
        )

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
        self.assertEqual(
            order.amount_total,
            0,
            "The promotion program should not make the order total go below 0",
        )
        self.assertEqual(order.amount_tax, 0)
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            0,
            "The promotion program should not be altered after recomputation",
        )
        self.assertEqual(order.amount_tax, 0)

        order.line_ids[3:].unlink()
        order._remove_program_from_points(coupon_program)
        order._remove_program_from_points(self.p1)

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids), 3, "The promotion program should be removed"
        )
        self._apply_promo_code(order, coupon.code)
        self.assertEqual(
            order.amount_total,
            10.0,
            "The promotion program should be correctly applied",
        )
        self._apply_promo_code(order, "test_10pc")
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            9.0,
            "The promotion program should not make the order total go below 0",
        )
        self.assertEqual(order.amount_tax, 0.27)
        self.assertEqual(order.amount_untaxed, 8.73)
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            order.amount_total,
            9.0,
            "The promotion program should not make the order total go below 0",
        )
        self.assertEqual(order.amount_tax, 0.27)
        self.assertEqual(order.amount_untaxed, 8.73)

    def test_program_discount_on_multiple_specific_products(self):
        order = self.empty_order
        self.p3.active = False
        p_specific_products = self.env["loyalty.program"].create(
            {
                "name": "20% reduction on Conference Chair and Drawer Black in cart",
                "program_type": "promotion",
                "trigger": "auto",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 25,
                            "discount_applicability": "specific",
                            "discount_product_ids": [
                                (6, 0, [self.conferenceChair.id, self.drawerBlack.id])
                            ],
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= p_specific_products

        self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conference Chair",
                "product_qty": 4.0,
                "order_id": order.id,
            }
        )
        sol2 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "Drawer Black",
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "Conference Chair + Drawer Black + 20% discount line",
        )
        self.assertEqual(
            order.amount_total, 87.00, "Total should be 87.00, see above comment"
        )

        p_specific_products.reward_ids.discount_product_ids = [
            (6, 0, [self.conferenceChair.id])
        ]
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "Should still be Conference Chair + Drawer Black + 20% discount line",
        )
        self.assertEqual(
            order.amount_total,
            99.50,
            "The 12.50 discount from the drawer black should be gone",
        )

        p_specific_products.reward_ids.discount_product_ids = [
            (6, 0, [self.conferenceChair.id, self.drawerBlack.id])
        ]

        percent_tax = self.env["account.tax"].create(
            {
                "name": "30% Tax",
                "amount_type": "percent",
                "amount": 30,
                "price_include_override": "tax_included",
            }
        )
        sol2.tax_ids = percent_tax

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            4,
            "Conference Chair + Drawer Black + 20% on no TVA product (Conference Chair) + 20% on 15% tva product (Drawer Black)",
        )
        self.assertEqual(
            order.amount_total, 87.00, "Total untaxed should be as per above comment"
        )
        self.assertEqual(
            order.amount_untaxed,
            78.35,
            "Total with taxes should be as per above comment",
        )

    def test_program_numbers_free_prod_with_min_amount_and_qty_on_same_prod(self):

        order = self.empty_order
        self.p3.active = False
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "Buy 2 Chairs, get 1 free",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.conferenceChair,
                            "reward_point_mode": "order",
                            "minimum_qty": 2,
                            "minimum_amount": self.conferenceChair.lst_price * 2,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.conferenceChair.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conf Chair",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        sol2 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "Drawer",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 2, "The promotion lines should not be applied"
        )
        sol1.write({"product_qty": 2.0})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 3, "The promotion lines should have been added"
        )
        self.assertEqual(
            order.amount_total,
            58.0,
            "The promotion line was not applied to the amount total",
        )
        sol2.unlink()
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "The other product should not affect the promotion",
        )
        self.assertEqual(
            order.amount_total,
            33.0,
            "The promotion line was not applied to the amount total",
        )
        sol1.write({"product_qty": 1.0})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(
            len(order.line_ids.ids), 1, "The promotion lines should have been removed"
        )

    def test_program_step_percentages(self):
        testprod = self.env["product.product"].create(
            {
                "name": "testprod",
                "lst_price": 118.0,
            }
        )

        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "10% discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "minimum_amount": 1500.00,
                            "minimum_amount_tax_mode": "incl",
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "15% discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "minimum_amount": 1750.00,
                            "minimum_amount_tax_mode": "incl",
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 15,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "20% discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "minimum_amount": 2000.00,
                            "minimum_amount_tax_mode": "incl",
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 20,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "25% discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "order",
                            "minimum_amount": 2500.00,
                            "minimum_amount_tax_mode": "incl",
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 25,
                            "discount_mode": "percent",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        order_line = self.env["sale.order.line"].create(
            {
                "product_id": testprod.id,
                "name": "testprod",
                "product_qty": 14.0,
                "price_unit": 118.0,
                "order_id": order.id,
                "tax_ids": False,
            }
        )
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_total, 1486.80, "10% discount should be applied")
        self.assertEqual(len(order.line_ids.ids), 2, "discount should be applied")

        order_line.write({"product_qty": 15})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_total, 1504.5, "15% discount should be applied")
        self.assertEqual(
            len(order.line_ids.ids), 2, "No discount applied while it should"
        )

        order_line.write({"product_qty": 17})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_total, 1604.8, "Discount improperly applied")
        self.assertEqual(
            len(order.line_ids.ids), 2, "No discount applied while it should"
        )

        order_line.write({"product_qty": 20})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_total, 1888.0, "Discount improperly applied")
        self.assertEqual(
            len(order.line_ids.ids), 2, "No discount applied while it should"
        )

        order_line.write({"product_qty": 14})
        self._auto_rewards(order, self.all_programs)
        self.assertEqual(order.amount_total, 1486.80, "Discount improperly applied")
        self.assertEqual(
            len(order.line_ids.ids), 2, "No discount applied while it should"
        )

    def test_program_free_prods_with_min_qty_and_reward_qty_and_rule(self):
        order = self.empty_order
        coupon_program = self.env["loyalty.program"].create(
            {
                "name": "2 free conference chair if at least 1 large cabinet",
                "trigger": "with_code",
                "program_type": "coupons",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.largeCabinet,
                            "reward_point_mode": "order",
                            "minimum_qty": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 100,
                            "discount_mode": "percent",
                            "discount_applicability": "specific",
                            "discount_product_ids": self.conferenceChair,
                            "discount_max_amount": 200,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        self.largeCabinet.write(
            {
                "list_price": 500,
                "sale_ok": True,
            }
        )
        self.conferenceChair.write({"list_price": 100, "sale_ok": True})

        self.env["sale.order.line"].create(
            {
                "product_id": self.largeCabinet.id,
                "name": "Large Cabinet",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        sol2 = self.env["sale.order.line"].create(
            {
                "product_id": self.conferenceChair.id,
                "name": "Conference chair",
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )

        self.assertEqual(
            len(order.line_ids),
            2,
            "The order must contain 2 order lines since the coupon is not yet applied",
        )
        self.assertEqual(
            order.amount_total,
            700.0,
            "The price must be 500.0 since the coupon is not yet applied",
        )

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

        self.assertEqual(
            len(order.line_ids),
            3,
            "The order must contain 3 order lines including one for free conference chair",
        )
        self.assertEqual(
            order.amount_total,
            500.0,
            "The price must be 500.0 since two conference chairs are free",
        )
        self.assertEqual(
            order.line_ids[2].price_total,
            -200.0,
            "The last order line should apply a reduction of 200.0 since there are two conference chairs that cost 100.0 each",
        )

        sol2.product_qty = 1.0
        self._auto_rewards(order, self.all_programs)

        self.assertEqual(
            order.amount_total,
            500.0,
            "The price must be 500.0 since two conference chairs are free and the user only bought one",
        )
        self.assertEqual(
            order.line_ids[2].price_total,
            -100.0,
            "The last order line should apply a reduction of 100.0 since there is one conference chair that cost 100.0",
        )

    def test_program_free_product_different_than_rule_product_with_multiple_application(
        self,
    ):
        order = self.empty_order

        self.p3.active = False
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "Buy 1 drawer black, get a free Large Meeting Table",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.drawerBlack,
                            "reward_point_mode": "order",
                            "minimum_qty": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 100,
                            "discount_mode": "percent",
                            "discount_applicability": "specific",
                            "discount_product_ids": self.largeMeetingTable,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )
        sol_B = self.env["sale.order.line"].create(
            {
                "product_id": self.largeMeetingTable.id,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, self.all_programs)

        self.assertEqual(
            len(order.line_ids),
            3,
            "The order must contain 3 order lines: 1x for Black Drawer, 1x for Large Meeting Table and 1x for free Large Meeting Table",
        )
        self.assertEqual(
            order.amount_total,
            self.drawerBlack.list_price * 2,
            "The price must be 50.0 since the Large Meeting Table is free: 2*25.00 (Black Drawer) + 1*40000.00 (Large Meeting Table) - 1*40000.00 (free Large Meeting Table)",
        )

        sol_B.product_qty = 2

        self._auto_rewards(order, self.all_programs)

        self.assertEqual(
            len(order.line_ids),
            3,
            "The order must contain 3 order lines: 1x for Black Drawer, 1x for Large Meeting Table and 1x for free Large Meeting Table",
        )
        self.assertEqual(
            order.amount_total,
            self.drawerBlack.list_price * 2,
            "The price must be 50.0 since the 2 Large Meeting Table are free: 2*25.00 (Black Drawer) + 2*40000.00 (Large Meeting Table) - 2*40000.00 (free Large Meeting Table)",
        )

    def test_program_modify_reward_line_qty(self):
        order = self.empty_order
        product_F = self.env["product.product"].create(
            {
                "name": "Product F",
                "list_price": 100,
                "sale_ok": True,
                "taxes_id": [(6, 0, [])],
            }
        )
        self.all_programs |= self.env["loyalty.program"].create(
            {
                "name": "1 Product F = 5$ discount",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": product_F,
                            "reward_point_mode": "order",
                            "minimum_qty": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 5,
                            "discount_mode": "per_point",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        self.env["sale.order.line"].create(
            {
                "product_id": product_F.id,
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, self.all_programs)

        self.assertEqual(
            len(order.line_ids),
            2,
            "The order must contain 2 order lines: 1x Product F and 1x 5$ discount",
        )
        self.assertEqual(
            order.amount_total,
            195.0,
            "The price must be 195.0 since there is a 5$ discount and 2x Product F",
        )
        self.assertEqual(
            sum(
                order.line_ids.filtered(lambda x: x.is_reward_line).mapped(
                    "product_qty"
                )
            ),
            1,
            "The reward line should have a quantity of 1 since Fixed Amount discounts apply only once per Sale Order",
        )

        order.line_ids[1].product_qty = 2

        self.assertEqual(
            len(order.line_ids),
            2,
            "The order must contain 2 order lines: 1x Product F and 1x 5$ discount",
        )
        self.assertEqual(
            order.amount_total,
            190.0,
            "The price must be 190.0 since there is now 2x 5$ discount and 2x Product F",
        )
        self.assertEqual(
            order.line_ids.filtered(lambda x: x.is_reward_line).price_unit,
            -5,
            "The discount unit price should still be -5 after the quantity was manually changed",
        )

    def test_program_multi_product_max_discount(self):
        order = self.empty_order
        coupon_program = self.env["loyalty.program"].create(
            {
                "name": "50% off for cheapest product(max $30)",
                "trigger": "with_code",
                "program_type": "coupons",
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 50,
                            "discount_mode": "percent",
                            "discount_applicability": "cheapest",
                            "discount_max_amount": 30,
                        },
                    )
                ],
            }
        )

        self.env["sale.order.line"].create(
            {
                "product_id": self.largeCabinet.id,
                "product_qty": 2.0,
                "order_id": order.id,
            }
        )

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

        self.assertEqual(len(order.line_ids), 2, "The order must contain 2 order lines")
        self.assertEqual(
            order.amount_total,
            610.0,
            "The price must be 610.0 since the max discount is 30",
        )

    def test_specific_discount_product_group(self):
        product_a, product_b, product_c = self.env["product.product"].create(
            [
                {
                    "name": "Product A",
                    "list_price": 6,
                    "sale_ok": True,
                    "taxes_id": [(6, 0, [])],
                },
                {
                    "name": "Product B",
                    "list_price": 4,
                    "sale_ok": True,
                    "taxes_id": [(6, 0, [])],
                },
                {
                    "name": "Product C",
                    "list_price": 10,
                    "sale_ok": True,
                    "taxes_id": [(6, 0, [])],
                },
            ]
        )
        programs = self.env["loyalty.program"].create(
            [
                {
                    "name": "-5 USD on [A, B]",
                    "trigger": "auto",
                    "program_type": "promotion",
                    "applies_on": "current",
                    "rule_ids": [(0, 0, {})],
                    "reward_ids": [
                        (
                            0,
                            0,
                            {
                                "reward_type": "discount",
                                "discount": 5,
                                "discount_mode": "per_point",
                                "discount_applicability": "specific",
                                "discount_product_ids": product_a | product_b,
                                "required_points": 1,
                            },
                        )
                    ],
                },
                {
                    "name": "-10 USD on A",
                    "trigger": "auto",
                    "program_type": "promotion",
                    "applies_on": "current",
                    "rule_ids": [(0, 0, {})],
                    "reward_ids": [
                        (
                            0,
                            0,
                            {
                                "reward_type": "discount",
                                "discount": 10,
                                "discount_mode": "per_point",
                                "discount_applicability": "specific",
                                "discount_product_ids": product_a,
                                "required_points": 1,
                            },
                        )
                    ],
                },
            ]
        )
        order = self.empty_order
        self.env["sale.order.line"].create(
            [
                {
                    "product_id": product_a.id,
                    "name": "Product A",
                    "product_qty": 1,
                    "order_id": order.id,
                },
                {
                    "product_id": product_b.id,
                    "name": "Product B",
                    "product_qty": 1,
                    "order_id": order.id,
                },
                {
                    "product_id": product_c.id,
                    "name": "Product C",
                    "product_qty": 1,
                    "order_id": order.id,
                },
            ]
        )
        self._auto_rewards(order, programs)
        self.assertEqual(order.amount_total, 10, "The total should be 10$.")
        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(order.amount_total, 9, "The total should be 9$.")
        order.line_ids.filtered("reward_id").unlink()
        self._apply_promo_code(order, "test_10pc")
        self.assertEqual(order.amount_total, 18, "The total should be 9$.")
        self._auto_rewards(order, programs)
        self.assertEqual(order.amount_total, 9, "The total should be 9$.")

    def test_specific_discount_multiple_taxes(self):
        product_a, product_b = self.env["product.product"].create(
            [
                {
                    "name": "Product A",
                    "list_price": 10,
                    "sale_ok": True,
                    "taxes_id": [(6, 0, [self.tax_10pc_excl.id])],
                },
                {
                    "name": "Product B",
                    "list_price": 10,
                    "sale_ok": True,
                    "taxes_id": [(6, 0, [self.tax_20pc_excl.id])],
                },
            ]
        )
        program_a, program_b = self.env["loyalty.program"].create(
            [
                {
                    "name": "-100% on A",
                    "trigger": "auto",
                    "program_type": "promotion",
                    "applies_on": "current",
                    "rule_ids": [(0, 0, {})],
                    "reward_ids": [
                        (
                            0,
                            0,
                            {
                                "reward_type": "discount",
                                "discount": 100,
                                "discount_mode": "percent",
                                "discount_applicability": "specific",
                                "discount_product_ids": product_a,
                                "required_points": 1,
                            },
                        )
                    ],
                },
                {
                    "name": "-5 USD on [A, B]",
                    "trigger": "auto",
                    "program_type": "promotion",
                    "applies_on": "current",
                    "rule_ids": [(0, 0, {})],
                    "reward_ids": [
                        (
                            0,
                            0,
                            {
                                "reward_type": "discount",
                                "discount": 5,
                                "discount_mode": "per_point",
                                "discount_applicability": "specific",
                                "discount_product_ids": product_a | product_b,
                                "required_points": 1,
                            },
                        )
                    ],
                },
            ]
        )

        order = self.empty_order
        self.env["sale.order.line"].create(
            [
                {
                    "product_id": product_a.id,
                    "name": "Product A",
                    "product_qty": 1,
                    "order_id": order.id,
                },
                {
                    "product_id": product_b.id,
                    "name": "Product B",
                    "product_qty": 1,
                    "order_id": order.id,
                },
            ]
        )
        self._auto_rewards(order, program_a)
        self.assertEqual(order.amount_total, 12, "Total should be 12$")
        self._auto_rewards(order, program_b)
        self.assertAlmostEqual(order.amount_total, 7, 0, "Total should be 7$")
        order.line_ids.filtered("reward_id").unlink()
        self._auto_rewards(order, program_b)
        self.assertAlmostEqual(order.amount_total, 18, 0, "Total should be 18$")
        self._auto_rewards(order, program_a)
        self.assertAlmostEqual(order.amount_total, 9.4, 1, "Total should be 9.4$")

    def test_fixed_amount_taxes_attribution(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "-5 USD",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 5,
                            "discount_mode": "per_point",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        sol = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertEqual(
            order.amount_total, 5, "Price should be 10$ - 5$(discount) = 5$"
        )
        self.assertEqual(order.amount_tax, 0, "No taxes are applied yet")

        sol.tax_ids = self.tax_10pc_base_incl
        self._auto_rewards(order, program)

        self.assertEqual(
            order.amount_total, 5, "Price should be 10$ - 5$(discount) = 5$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 5 / 11, precision_rounding=3),
            0,
            "10% Tax included in 5$",
        )

        sol.tax_ids = self.tax_10pc_excl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 6, 1, msg="Price should be 11$ - 5$(discount) = 6$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 6 / 11, precision_rounding=3),
            0,
            "10% Tax included in 6$",
        )

        sol.tax_ids = self.tax_20pc_excl
        self._auto_rewards(order, program)

        self.assertEqual(
            order.amount_total, 7, "Price should be 12$ - 5$(discount) = 7$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 7 / 12, precision_rounding=3),
            0,
            "20% Tax included on 7$",
        )

        sol.tax_ids = self.tax_10pc_base_incl + self.tax_10pc_excl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 6, 1, msg="Price should be 11$ - 5$(discount) = 6$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 6 / 12, precision_rounding=3),
            0,
            "20% Tax included on 6$",
        )

    def test_fixed_amount_taxes_attribution_multiline(self):

        program = self.env["loyalty.program"].create(
            {
                "name": "-5 USD",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 5,
                            "discount_mode": "per_point",
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        sol2 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 15, 1, msg="Price should be 20$ - 5$(discount) = 15$"
        )
        self.assertEqual(order.amount_tax, 0, "No taxes are applied yet")

        sol1.tax_ids = self.tax_10pc_base_incl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 15, 1, msg="Price should be 20$ - 5$(discount) = 15$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 5 / 11 + 0, precision_rounding=3),
            0,
            "10% Tax included in 5$ in sol1 (highest cost) and 0 in sol2",
        )

        sol2.tax_ids = self.tax_10pc_excl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 16, 1, msg="Price should be 21$ - 5$(discount) = 16$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 5 / 11, precision_rounding=3), 0
        )

        sol2.tax_ids = self.tax_10pc_base_incl + self.tax_10pc_excl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 16, 1, msg="Price should be 21$ - 5$(discount) = 16$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 21.45 / 11, precision_rounding=3), 0
        )

        sol3 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        sol3.tax_ids = self.tax_10pc_excl
        self._auto_rewards(order, program)

        self.assertAlmostEqual(
            order.amount_total, 27, 1, msg="Price should be 32$ - 5$(discount) = 27$"
        )
        self.assertEqual(
            float_compare(order.amount_tax, 32.45 / 11, precision_rounding=3), 0
        )

    def test_fixed_amount_with_negative_cost(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "-10 USD",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
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
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order

        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "name": "hand discount",
                "price_unit": -5,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 3, "Promotion should add 1 line")
        self.assertEqual(
            order.amount_total, 0, "10$ discount should cover the whole price"
        )

        sol1.price_unit = 20
        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 3, "Promotion should add 1 line")
        self.assertEqual(
            order.amount_total,
            5,
            "10$ discount should be applied on top of the 15$ original price",
        )

    def test_fixed_amount_change_promo_amount(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "-10 USD",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
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
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order

        self.env["sale.order.line"].create(
            {
                "product_id": self.drawerBlack.id,
                "price_unit": 10,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        self.assertEqual(order.amount_total, 0, "10$ - 10$(discount) = 0$(total) ")

        program.reward_ids.discount = 5
        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        self.assertEqual(order.amount_total, 5, "10$ - 5$(discount) = 5$(total) ")

    def test_fixed_tax_not_affected(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "50% discount",
                "program_type": "promotion",
                "trigger": "auto",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 50,
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        self.tax_10_fixed = self.env["account.tax"].create(
            {
                "name": "10$ Fixed tax",
                "amount_type": "fixed",
                "amount": 10,
            }
        )

        self.product_A.write({"list_price": 100})
        self.product_A.taxes_id = self.tax_15pc_excl + self.tax_10_fixed

        self.env["sale.order.line"].create(
            {
                "product_id": self.product_A.id,
                "name": "product A",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        self.assertEqual(
            order.amount_total,
            67.5,
            "100$ + 15% tax + 10$ tax - 50%(discount) = 67.5$(total) ",
        )
        self.assertEqual(
            order.amount_tax,
            17.5,
            "15% tax + 10$ tax$ - 50%$(discount) = 17.5$(total) ",
        )

    def test_fixed_tax_not_affected_2(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "50$ discount",
                "program_type": "promotion",
                "trigger": "auto",
                "applies_on": "current",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "per_order",
                            "discount": 50,
                            "discount_applicability": "order",
                            "required_points": 1,
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        self.tax_10_fixed = self.env["account.tax"].create(
            {
                "name": "10$ Fixed tax",
                "amount_type": "fixed",
                "amount": 10,
            }
        )

        self.product_A.write({"list_price": 100})
        self.product_A.taxes_id = self.tax_15pc_excl + self.tax_10_fixed

        self.env["sale.order.line"].create(
            {
                "product_id": self.product_A.id,
                "name": "product A",
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )

        self._auto_rewards(order, program)

        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        self.assertEqual(
            order.amount_total,
            75,
            "100$ + 15% tax + 10$ tax - 50$(discount) = 75$(total) ",
        )

    def test_loyalty_card_tax_total(self):
        loyalty_program = self.env["loyalty.program"].create(
            {
                "name": "Test loyalty card",
                "program_type": "loyalty",
                "trigger": "auto",
                "applies_on": "both",
                "rule_ids": [
                    Command.create(
                        {
                            "reward_point_mode": "money",
                            "reward_point_amount": 0.01,
                        }
                    )
                ],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount_mode": "per_point",
                            "discount": 1,
                            "discount_applicability": "cheapest",
                            "required_points": 1,
                        }
                    )
                ],
            }
        )
        order = self.empty_order
        self.env["loyalty.card"].create(
            [
                {
                    "program_id": loyalty_program.id,
                    "partner_id": order.partner_id.id,
                    "points": 3.39,
                }
            ]
        )

        tax_15pc_excl = self.env["account.tax"].create(
            {
                "name": "15% Tax excl",
                "amount_type": "percent",
                "amount": 15,
            }
        )

        self.product_A.write(
            {"list_price": 140.0, "taxes_id": [Command.set(tax_15pc_excl.ids)]}
        )

        order.line_ids = [
            Command.create(
                {
                    "product_id": self.product_A.id,
                }
            ),
        ]

        self._auto_rewards(order, loyalty_program)

        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        self.assertEqual(order.line_ids[0].tax_ids, tax_15pc_excl)
        self.assertEqual(order.line_ids[1].tax_ids, tax_15pc_excl)
        self.assertEqual(order.amount_total, 156.0, "140$ + 15% - 5$ = 156$")

    def test_rounded_used_loyalty_points(self):
        loyalty_program = self.env["loyalty.program"].create(
            {
                "name": "Test loyalty card",
                "program_type": "loyalty",
                "trigger": "auto",
                "applies_on": "both",
                "rule_ids": [Command.set([])],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount_mode": "per_point",
                            "discount": 0.03,
                            "discount_applicability": "order",
                            "required_points": 1,
                        }
                    )
                ],
            }
        )
        order = self.empty_order
        self.env["loyalty.card"].create(
            [
                {
                    "program_id": loyalty_program.id,
                    "partner_id": order.partner_id.id,
                    "points": 3030,
                }
            ]
        )
        product_a = self._create_product(
            name="product_a",
            lst_price=3000.0,
            taxes_id=[Command.set([])],
        )
        order.line_ids = [Command.create({"product_id": product_a.id})]

        coupon = loyalty_program.coupon_ids[0]
        order._apply_program_reward(loyalty_program.reward_ids[0], coupon)
        order.action_confirm()
        self.assertEqual(len(order.line_ids), 2, "Promotion should add 1 line")
        used_points = coupon.history_ids[0].used
        self.assertEqual(used_points, coupon.currency_id.round(used_points))

    def test_apply_order_and_specific_discounts(self):
        order_program, specific_program = self.env["loyalty.program"].create(
            [
                {
                    "name": "$50 discount",
                    "program_type": "promotion",
                    "trigger": "auto",
                    "applies_on": "current",
                    "rule_ids": [Command.create({})],
                    "reward_ids": [
                        Command.create(
                            {
                                "reward_type": "discount",
                                "discount_mode": "per_order",
                                "discount": 50,
                                "discount_applicability": "order",
                                "required_points": 1,
                            }
                        )
                    ],
                },
                {
                    "name": "$10 discount on Pedal Bin",
                    "program_type": "promotion",
                    "trigger": "auto",
                    "applies_on": "current",
                    "rule_ids": [Command.create({})],
                    "reward_ids": [
                        Command.create(
                            {
                                "reward_type": "discount",
                                "discount_mode": "per_order",
                                "discount": 10,
                                "discount_applicability": "specific",
                                "discount_product_ids": self.pedalBin.ids,
                                "required_points": 1,
                            }
                        )
                    ],
                },
            ]
        )
        order = self.empty_order
        order.line_ids = [
            Command.create(
                {
                    "product_id": self.pedalBin.id,
                    "tax_ids": self.tax_20pc_excl.ids,
                }
            )
        ]

        self.assertAlmostEqual(
            order.amount_total,
            self.pedalBin.list_price * (1 + self.tax_20pc_excl.amount / 100),
            msg="Order total should equal product list price plus taxes",
        )

        self._auto_rewards(order, order_program)
        self.assertAlmostEqual(
            order.amount_total,
            self.pedalBin.list_price * (1 + self.tax_20pc_excl.amount / 100) - 50,
            msg="The order total should be $50 less than initially after the discount is applied.",
        )

        self._auto_rewards(order, specific_program)
        self.assertFalse(
            order.amount_total,
            "Order total should be 0, as a specific discount should have been applied.",
        )
