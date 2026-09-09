from odoo.fields import Command
from odoo.tests import Form, tagged

from odoo.addons.sale_loyalty.tests.common import TestSaleCouponCommon


@tagged("post_install", "-at_install")
class TestSaleCouponProgramRules(TestSaleCouponCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.iPadMini = cls.env["product.product"].create(
            {"name": "Large Cabinet", "list_price": 320.0}
        )
        tax_15pc_excl = cls.env["account.tax"].create(
            {
                "name": "15% Tax excl",
                "amount_type": "percent",
                "amount": 15,
            }
        )
        cls.product_delivery_poste = cls.env["product.product"].create(
            {
                "name": "The Poste",
                "type": "service",
                "categ_id": cls.env.ref("delivery.product_category_deliveries").id,
                "sale_ok": False,
                "purchase_ok": False,
                "list_price": 20.0,
                "taxes_id": [(6, 0, [tax_15pc_excl.id])],
            }
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "The Poste",
                "fixed_price": 20.0,
                "delivery_type": "base_on_rule",
                "product_id": cls.product_delivery_poste.id,
            }
        )
        cls.env["delivery.price.rule"].create(
            [
                {
                    "carrier_id": cls.carrier.id,
                    "max_value": 5,
                    "list_base_price": 20,
                },
                {
                    "carrier_id": cls.carrier.id,
                    "operator": ">=",
                    "max_value": 5,
                    "list_base_price": 50,
                },
                {
                    "carrier_id": cls.carrier.id,
                    "operator": ">=",
                    "max_value": 300,
                    "variable": "price",
                    "list_base_price": 0,
                },
            ]
        )

    def test_free_shipping_reward(self):
        self.immediate_promotion_program.active = False
        program = self.env["loyalty.program"].create(
            {
                "name": "Free Shipping if at least 100 euros",
                "trigger": "auto",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "minimum_amount": 100,
                            "minimum_amount_tax_mode": "incl",
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "shipping",
                        },
                    )
                ],
            }
        )

        order = self.empty_order

        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_B.id,
                            "name": "Product B",
                            "product_qty": 1.0,
                        },
                    )
                ]
            }
        )
        self._auto_rewards(order, program)
        self.assertEqual(len(order.line_ids.ids), 1)

        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {
                    "default_order_id": order.id,
                    "default_carrier_id": self.env["delivery.carrier"].search([])[1],
                }
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()

        self._auto_rewards(order, program)
        self.assertEqual(len(order.line_ids.ids), 2)

        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_B.id,
                            "name": "Product 1B",
                            "product_qty": 1.0,
                            "price_unit": 81.74,
                        },
                    )
                ]
            }
        )
        self._auto_rewards(order, program)
        self.assertEqual(len(order.line_ids.ids), 3)

        order.write(
            {
                "line_ids": [
                    (
                        0,
                        False,
                        {
                            "product_id": self.product_A.id,
                            "name": "Product 1",
                            "product_qty": 1.0,
                            "price_unit": 0.30,
                        },
                    )
                ]
            }
        )

        self._auto_rewards(order, program)
        self.assertEqual(len(order.line_ids.ids), 5)

        order.write(
            {
                "line_ids": [
                    (
                        2,
                        order.line_ids.filtered(
                            lambda line: line.product_id.id == self.product_A.id
                        ).id,
                        False,
                    )
                ]
            }
        )
        self._auto_rewards(order, program)
        self.assertEqual(len(order.line_ids.ids), 3)

    def test_shipping_cost(self):
        p_minimum_threshold_free_delivery = self.env["loyalty.program"].create(
            {
                "name": "free shipping if > 872 tax excl",
                "trigger": "auto",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "minimum_amount": 872,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "shipping",
                        },
                    )
                ],
            }
        )
        p_2 = self.env["loyalty.program"].create(
            {
                "name": "10% reduction if > 872 tax excl",
                "trigger": "auto",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "minimum_amount": 872,
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
                        },
                    )
                ],
            }
        )
        programs = p_minimum_threshold_free_delivery | p_2
        order = self.empty_order
        self.iPadMini.taxes_id = self.tax_10pc_incl
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.iPadMini.id,
                "name": "Large Cabinet",
                "product_qty": 3.0,
                "order_id": order.id,
            }
        )
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "We should get the 10% discount line since we bought 872.73$ and a free shipping line with a value of 0",
        )
        self.assertEqual(
            order.line_ids.filtered(
                lambda l: l.reward_id.reward_type == "shipping"
            ).price_unit,
            0,
        )
        self.assertEqual(order.amount_total, 960 * 0.9)
        order.carrier_id = self.env["delivery.carrier"].search([])[1]

        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {
                    "default_order_id": order.id,
                    "default_carrier_id": self.env["delivery.carrier"].search([])[1],
                }
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()

        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            4,
            "We should get both rewards regardless of applying order.",
        )

        p_minimum_threshold_free_delivery.sequence = 10
        (order.line_ids - sol1).unlink()
        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {
                    "default_order_id": order.id,
                    "default_carrier_id": self.env["delivery.carrier"].search([])[1],
                }
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            4,
            "We should get both rewards regardless of applying order.",
        )

    def test_shipping_cost_numbers(self):
        p_1 = self.env["loyalty.program"].create(
            {
                "name": "Free shipping if > 872 tax excl",
                "trigger": "with_code",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "mode": "with_code",
                            "code": "free_shipping",
                            "minimum_amount": 872,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "shipping",
                        },
                    )
                ],
            }
        )
        p_2 = self.env["loyalty.program"].create(
            {
                "name": "Buy 4 large cabinet, get one for free",
                "trigger": "auto",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "product_ids": self.iPadMini,
                            "minimum_qty": 4,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "product",
                            "reward_product_id": self.iPadMini.id,
                            "reward_product_qty": 1,
                            "required_points": 1,
                        },
                    )
                ],
            }
        )
        programs = p_1 | p_2
        order = self.empty_order
        self.iPadMini.taxes_id = self.tax_10pc_incl
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.iPadMini.id,
                "name": "Large Cabinet",
                "product_qty": 3.0,
                "order_id": order.id,
            }
        )

        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {"default_order_id": order.id, "default_carrier_id": self.carrier.id}
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()
        self._auto_rewards(order, programs)
        self.assertEqual(len(order.line_ids.ids), 2)
        self.assertEqual(order.reward_amount, 0)
        self.assertEqual(
            sum(line.price_total for line in order._get_no_effect_on_threshold_lines()),
            23,
        )
        self.assertEqual(order.amount_untaxed, 872.73 + 20)

        self._apply_promo_code(order, "free_shipping")
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "We should get the delivery line and the free delivery since we are below 872.73$",
        )
        self.assertEqual(order.reward_amount, -20)
        self.assertEqual(
            sum(line.price_total for line in order._get_no_effect_on_threshold_lines()),
            0,
        )
        self.assertEqual(order.amount_untaxed, 872.73)

        sol1.product_qty = 4
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids), 4, "We should get a free Large Cabinet"
        )
        self.assertEqual(order.reward_amount, -20 - 320)
        self.assertEqual(
            sum(line.price_total for line in order._get_no_effect_on_threshold_lines()),
            0,
        )
        self.assertEqual(order.amount_untaxed, 1163.64)

        programs |= self.env["loyalty.program"].create(
            {
                "name": "20% reduction on large cabinet in cart",
                "trigger": "auto",
                "rule_ids": [(0, 0, {})],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount": 20,
                            "discount_mode": "percent",
                            "discount_applicability": "cheapest",
                        },
                    )
                ],
            }
        )
        self._auto_rewards(order, programs)
        self.assertAlmostEqual(
            order.amount_untaxed,
            1105.45,
            2,
            "One large cabinet should be discounted by 20%",
        )

    def test_free_shipping_reward_last_line(self):
        self.immediate_promotion_program.active = False
        loyalty_program = self.env["loyalty.program"].create(
            {
                "name": "GIFT Free Shipping",
                "program_type": "loyalty",
                "applies_on": "both",
                "trigger": "auto",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_mode": "money",
                            "reward_point_amount": 1,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "shipping",
                            "required_points": 100,
                        },
                    )
                ],
            }
        )
        self.env["loyalty.card"].create(
            {
                "program_id": loyalty_program.id,
                "partner_id": self.partner.id,
                "points": 250,
            }
        )
        order = self.empty_order
        order._update_programs_and_rewards()
        claimable_rewards = order._get_claimable_rewards()
        self.assertEqual(len(claimable_rewards), 1)
        self.assertTrue(self._claim_reward(order, loyalty_program))

    def test_nothing_delivered_nothing_to_invoice(self):
        program = self.env["loyalty.program"].create(
            {
                "name": "10% reduction on all orders",
                "trigger": "auto",
                "program_type": "promotion",
                "rule_ids": [
                    Command.create(
                        {
                            "minimum_amount": 50,
                        }
                    )
                ],
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
        product = self.env["product.product"].create(
            {
                "name": "Test product",
                "type": "consu",
                "list_price": 200.0,
                "invoice_policy": "transferred",
            }
        )
        order = self.empty_order
        self.env["sale.order.line"].create(
            {
                "product_id": product.id,
                "order_id": order.id,
            }
        )
        self._auto_rewards(order, program)
        self.assertNotEqual(order.reward_amount, 0)
        self.assertEqual(order.invoice_state, "no")
        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {"default_order_id": order.id, "default_carrier_id": self.carrier.id}
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()
        order.action_confirm()
        self.assertEqual(order.delivery_set, True)
        self.assertEqual(order.invoice_state, "no")

    def test_delivery_shant_count_toward_quantity_bought(self):

        discount_program = self.env["loyalty.program"].create(
            {
                "name": "10 percent off order with min. 2 products",
                "trigger": "auto",
                "program_type": "promotion",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "minimum_qty": 2,
                            "minimum_amount": 0,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 10.0,
                            "discount_applicability": "order",
                        },
                    )
                ],
            }
        )

        order = self.empty_order
        self.env["sale.order.line"].create(
            {
                "product_id": self.iPadMini.id,
                "name": self.iPadMini.name,
                "product_qty": 1.0,
                "order_id": order.id,
            }
        )
        self.env["sale.order.line"].create(
            {
                "product_id": self.product_delivery_poste.id,
                "name": "Free delivery charges\nFree Shipping",
                "product_qty": 1.0,
                "order_id": order.id,
                "is_delivery": True,
            }
        )

        self._auto_rewards(order, discount_program)

        err_msg = "No reward lines should be created as the delivery line shouldn't be included in the promotion calculation"
        self.assertEqual(len(order.line_ids.ids), 2, err_msg)

    def test_free_shipping_should_be_removed_when_rules_are_not_met(self):
        p_1 = self.env["loyalty.program"].create(
            {
                "name": "Free shipping if > 872 tax excl",
                "trigger": "with_code",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "mode": "with_code",
                            "code": "free_shipping",
                            "minimum_amount": 872,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_type": "shipping",
                        },
                    )
                ],
            }
        )
        programs = p_1
        order = self.empty_order
        self.iPadMini.taxes_id = self.tax_10pc_incl
        sol1 = self.env["sale.order.line"].create(
            {
                "product_id": self.iPadMini.id,
                "name": "Large Cabinet",
                "product_qty": 3.0,
                "order_id": order.id,
            }
        )

        delivery_wizard = Form(
            self.env["choose.delivery.carrier"].with_context(
                {"default_order_id": order.id, "default_carrier_id": self.carrier.id}
            )
        )
        choose_delivery_carrier = delivery_wizard.save()
        choose_delivery_carrier.button_confirm()
        self._auto_rewards(order, programs)
        self.assertEqual(len(order.line_ids.ids), 2)
        self.assertEqual(order.reward_amount, 0)
        self.assertEqual(
            sum(line.price_total for line in order._get_no_effect_on_threshold_lines()),
            23,
        )
        self.assertEqual(order.amount_untaxed, 872.73 + 20)

        self._apply_promo_code(order, "free_shipping")
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            3,
            "We should get the delivery line and the free delivery since we are below 872.73$",
        )
        self.assertEqual(order.reward_amount, -20)
        self.assertEqual(
            sum(line.price_total for line in order._get_no_effect_on_threshold_lines()),
            0,
        )
        self.assertEqual(order.amount_untaxed, 872.73)

        sol1.product_qty = 1
        self._auto_rewards(order, programs)
        self.assertEqual(
            len(order.line_ids.ids),
            2,
            "We should loose the free delivery reward since we are above 872.73$",
        )
        self.assertEqual(order.reward_amount, 0)

    def test_discount_reward_claimable_when_shipping_reward_already_claimed_from_same_coupon(
        self,
    ):
        program = self.env["loyalty.program"].create(
            {
                "name": "10% Discount & Shipping",
                "applies_on": "current",
                "trigger": "with_code",
                "program_type": "promotion",
                "rule_ids": [
                    Command.create({"mode": "with_code", "code": "10PERCENT&SHIPPING"})
                ],
                "reward_ids": [
                    Command.create(
                        {
                            "reward_type": "shipping",
                            "reward_product_qty": 1,
                        }
                    ),
                    Command.create(
                        {
                            "reward_type": "discount",
                            "discount": 10,
                            "discount_mode": "percent",
                            "discount_applicability": "specific",
                        }
                    ),
                ],
            }
        )

        coupon = self.env["loyalty.card"].create(
            {"program_id": program.id, "points": 20, "code": "GIFT_CARD"}
        )

        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [Command.create({"product_id": self.product_B.id})],
            }
        )

        ship_reward = program.reward_ids.filtered(
            lambda reward: reward.reward_type == "shipping"
        )
        discount_reward = program.reward_ids - ship_reward
        order._apply_program_reward(ship_reward, coupon)
        rewards = order._get_claimable_rewards()[coupon]
        msg = "The discount reward should still be applicable as only the shipping one was claimed."
        self.assertEqual(rewards, discount_reward, msg)
