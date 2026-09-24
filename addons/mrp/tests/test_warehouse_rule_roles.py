from odoo.tests import tagged

from odoo.addons.stock.tests.test_warehouse_rule_roles import WarehouseRuleRoleCase


@tagged("post_install", "-at_install")
class TestMrpWarehouseRuleRoles(WarehouseRuleRoleCase):
    def test_manufacture_rules_follow_steps_and_keep_hand_made_rules(self):
        warehouse = self.warehouse
        warehouse.manufacture_steps = "pbm_sam"
        user_rule = self.add_user_rule(
            warehouse.pbm_route_id,
            location_src_id=warehouse.lot_stock_id.id,
            location_dest_id=warehouse.pbm_loc_id.id,
            picking_type_id=warehouse.int_type_id.id,
        )
        for steps in ("pbm", "mrp_one_step", "pbm_sam", "pbm"):
            warehouse.manufacture_steps = steps
            with self.subTest(steps=steps):
                self.assertEqual(user_rule.active, warehouse.pbm_route_id.active)
                self.assert_route_follows_steps(warehouse, "pbm_route_id")

    def test_reception_rules_follow_steps_and_keep_hand_made_rules(self):
        warehouse = self.warehouse
        user_rule = self.add_user_rule(warehouse.reception_route_id)
        for steps in ("three_steps", "one_step", "two_steps"):
            warehouse.reception_steps = steps
            with self.subTest(steps=steps):
                self.assertTrue(user_rule.active)
                self.assert_route_follows_steps(warehouse, "reception_route_id")
        self.assertEqual(
            warehouse.manufacture_pull_id.warehouse_role, "manufacture_pull_id"
        )
