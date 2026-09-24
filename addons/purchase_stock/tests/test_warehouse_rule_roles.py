from odoo.modules.module import get_module_path, load_script
from odoo.tests import tagged

from odoo.addons.stock.tests.test_warehouse_rule_roles import WarehouseRuleRoleCase


@tagged("post_install", "-at_install")
class TestPurchaseWarehouseRuleRoles(WarehouseRuleRoleCase):
    def add_stock_era_reception_rule(self, **values):
        warehouse = self.warehouse
        return self.env["stock.rule"].create(
            {
                "name": "Vendors → Stock (stock-only era)",
                "route_id": warehouse.reception_route_id.id,
                "action": "pull",
                "location_src_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "picking_type_id": warehouse.in_type_id.id,
                "procure_method": "make_to_stock",
                "warehouse_id": warehouse.id,
                **values,
            }
        )

    def test_reception_rules_follow_steps_and_keep_hand_made_rules(self):
        warehouse = self.warehouse
        user_rule = self.add_user_rule(warehouse.reception_route_id)
        for steps in ("three_steps", "two_steps", "one_step", "three_steps"):
            warehouse.reception_steps = steps
            with self.subTest(steps=steps):
                self.assertTrue(user_rule.active)
                self.assert_route_follows_steps(warehouse, "reception_route_id")
        self.assertEqual(warehouse.buy_pull_id.warehouse_role, "buy_pull_id")

    def test_an_obsolete_stock_era_rule_is_archived_by_a_step_change(self):
        warehouse = self.warehouse
        obsolete = self.add_stock_era_reception_rule(
            warehouse_role="reception_route_id"
        )
        warehouse.reception_steps = "two_steps"
        self.assertFalse(
            obsolete.active,
            "purchase_stock replaced this routing; the generated rule must not "
            "survive only because no current routing names it",
        )
        self.assert_route_follows_steps(warehouse, "reception_route_id")

    def test_backfill_marks_a_legacy_stock_era_rule_so_reactivation_archives_it(self):
        warehouse = self.warehouse
        legacy = self.add_stock_era_reception_rule(active=False)
        self.assertFalse(legacy.warehouse_role)
        script = load_script(
            f"{get_module_path('stock')}/migrations/1.21/end-migrate_rule_roles.py",
            "stock_1_21_end_migrate_rule_roles",
        )
        script.migrate(self.env.cr, "1.20")
        self.env.invalidate_all()
        self.assertEqual(legacy.warehouse_role, "reception_route_id")

        warehouse.action_archive()
        warehouse.action_unarchive()
        self.assertFalse(legacy.active)
        self.assert_route_follows_steps(warehouse, "reception_route_id")
