from lxml import etree

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
        cost = self._landed_cost(target_model="picking")
        cost._onchange_target_model()
        self.assertFalse(cost.mrp_production_ids)

    def test_targeted_moves_empty_without_mo(self):
        cost = self._landed_cost(target_model="manufacturing")
        self.assertFalse(cost._get_targeted_move_ids())

    def _manufacturing_orders(self, count):
        product = self.env["product.product"].create(
            {"name": "MRP LC finished", "is_storable": True}
        )
        return self.env["mrp.production"].create(
            [{"product_id": product.id, "product_qty": 1.0} for _ in range(count)]
        )

    def test_mrp_production_count_follows_the_m2m(self):
        cost = self._landed_cost()
        self.assertEqual(cost.mrp_production_count, 0)
        orders = self._manufacturing_orders(2)
        cost.mrp_production_ids = orders
        self.assertEqual(cost.mrp_production_count, 2)

    def test_action_view_mrp_productions_lists_several(self):
        orders = self._manufacturing_orders(2)
        cost = self._landed_cost()
        cost.mrp_production_ids = orders
        action = cost.action_view_mrp_productions()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["view_mode"], "list,form")
        self.assertEqual(action["domain"], [("id", "in", orders.ids)])
        self.assertNotIn("res_id", action)

    def test_action_view_mrp_productions_opens_the_only_one(self):
        order = self._manufacturing_orders(1)
        cost = self._landed_cost()
        cost.mrp_production_ids = order
        action = cost.action_view_mrp_productions()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["view_mode"], "form")
        self.assertEqual(action["res_id"], order.id)

    def test_form_offers_the_manufacturing_stat_button(self):
        arch = etree.fromstring(
            self.env["stock.landed.cost"].get_view(
                self.env.ref("stock_landed_costs.view_stock_landed_cost_form").id
            )["arch"]
        )
        self.assertTrue(
            arch.xpath("//div[@name='button_box']"),
            "the landed cost form needs a button box to host the stat button",
        )
        self.assertTrue(
            arch.xpath("//button[@name='action_view_mrp_productions']"),
            "the manufacturing stat button is missing from the combined arch",
        )
