from odoo import Command
from odoo.modules.module import get_module_path, load_script
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.models.stock_rule import RESUPPLY_ROLE


def rule_shape(rule):
    return (
        rule.location_src_id.id,
        rule.location_dest_id.id,
        rule.picking_type_id.id,
        rule.action,
    )


def routing_shape(routing):
    return (
        routing.from_loc.id,
        routing.dest_loc.id,
        routing.picking_type.id,
        routing.action,
    )


class WarehouseRuleRoleCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["stock.rule"].with_context(active_test=False)
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "Role Warehouse", "code": "RWH"}
        )

    def expected_shapes(self, warehouse, route_field):
        routing_key = warehouse._prepare_route_vals()[route_field]["routing_key"]
        return {
            routing_shape(routing)
            for routing in warehouse._prepare_rule_routings()[warehouse.id][routing_key]
        }

    def active_generated_shapes(self, warehouse, route_field):
        return {
            rule_shape(rule)
            for rule in warehouse[route_field].rule_ids
            if rule.warehouse_role == route_field
        }

    def assert_route_follows_steps(self, warehouse, route_field):
        self.assertEqual(
            self.active_generated_shapes(warehouse, route_field),
            self.expected_shapes(warehouse, route_field),
            "the active generated rules of %s must be exactly the current routing"
            % route_field,
        )

    def add_user_rule(self, route, **values):
        warehouse = self.warehouse
        return self.env["stock.rule"].create(
            {
                "name": "Hand-made rule",
                "route_id": route.id,
                "action": "pull",
                "location_src_id": warehouse.wh_input_stock_loc_id.id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "picking_type_id": warehouse.int_type_id.id,
                "procure_method": "make_to_stock",
                **values,
            }
        )

    def roles_by_rule(self, rules):
        return {rule.id: rule.warehouse_role for rule in rules}

    def warehouse_rules(self, warehouse):
        return self.Rule.search(
            [
                "|",
                ("warehouse_id", "=", warehouse.id),
                (
                    "route_id",
                    "in",
                    warehouse.with_context(active_test=False).route_ids.ids,
                ),
            ]
        )


@tagged("post_install", "-at_install")
class TestWarehouseRuleRoles(WarehouseRuleRoleCase):
    def test_every_generated_rule_carries_its_slot(self):
        warehouse = self.warehouse
        warehouse.write(
            {"reception_steps": "three_steps", "delivery_steps": "pick_pack_ship"}
        )
        for route_field in warehouse._prepare_route_vals():
            route = warehouse[route_field]
            with self.subTest(route=route_field):
                self.assertTrue(route.rule_ids)
                self.assertEqual(
                    set(route.rule_ids.mapped("warehouse_role")), {route_field}
                )
        for rule_field in warehouse._get_global_rule_fields():
            if warehouse[rule_field]:
                self.assertEqual(warehouse[rule_field].warehouse_role, rule_field)

    def test_a_hand_made_rule_on_the_reception_route_survives_step_changes(self):
        warehouse = self.warehouse
        route = warehouse.reception_route_id
        user_rule = self.add_user_rule(route)
        self.assertFalse(user_rule.warehouse_role)
        for steps in ("two_steps", "three_steps", "one_step", "two_steps"):
            warehouse.reception_steps = steps
            with self.subTest(steps=steps):
                self.assertTrue(user_rule.active, "a step change archived a user rule")
                self.assert_route_follows_steps(warehouse, "reception_route_id")

    def test_a_hand_made_rule_on_the_delivery_route_survives_step_changes(self):
        warehouse = self.warehouse
        user_rule = self.add_user_rule(
            warehouse.delivery_route_id,
            location_src_id=warehouse.lot_stock_id.id,
            location_dest_id=warehouse.wh_output_stock_loc_id.id,
        )
        for steps in ("pick_ship", "pick_pack_ship", "ship_only"):
            warehouse.delivery_steps = steps
            with self.subTest(steps=steps):
                self.assertTrue(user_rule.active)
                self.assert_route_follows_steps(warehouse, "delivery_route_id")

    def test_a_hand_archived_rule_stays_archived_across_a_step_change(self):
        warehouse = self.warehouse
        user_rule = self.add_user_rule(warehouse.reception_route_id)
        user_rule.action_archive()
        warehouse.reception_steps = "two_steps"
        self.assertFalse(
            user_rule.active,
            "rewriting an already-active route cascaded an unarchive to its rules",
        )

    def test_a_hand_made_rule_survives_warehouse_reactivation(self):
        warehouse = self.warehouse
        warehouse.reception_steps = "three_steps"
        user_rule = self.add_user_rule(
            warehouse.reception_route_id, warehouse_id=warehouse.id
        )
        warehouse.action_archive()
        self.assertFalse(user_rule.active)
        warehouse.action_unarchive()
        self.assertTrue(user_rule.active, "reactivation archived a user rule")
        self.assert_route_follows_steps(warehouse, "reception_route_id")

    def test_a_copied_rule_is_not_generated_and_does_not_shadow_the_original(self):
        warehouse = self.warehouse
        warehouse.reception_steps = "two_steps"
        generated = warehouse.reception_route_id.rule_ids.filtered(
            lambda rule: rule.action == "push"
        )
        copy = generated.copy({"sequence": 1})
        self.assertFalse(copy.warehouse_role)
        warehouse.reception_steps = "three_steps"
        warehouse.reception_steps = "two_steps"
        self.assertTrue(generated.active, "sync adopted the copy over the original")
        self.assertTrue(copy.active)

    def test_resupply_rules_are_generated(self):
        supplier = self.env["stock.warehouse"].create(
            {"name": "Role Supplier", "code": "RSP", "delivery_steps": "pick_ship"}
        )
        self.warehouse.resupply_wh_ids = [Command.link(supplier.id)]
        route = self.env["stock.route"].search(
            [
                ("supplied_wh_id", "=", self.warehouse.id),
                ("supplier_wh_id", "=", supplier.id),
            ]
        )
        self.assertTrue(route.rule_ids)
        self.assertEqual(set(route.rule_ids.mapped("warehouse_role")), {RESUPPLY_ROLE})
        supplier.delivery_steps = "ship_only"
        mto_legs = self.Rule.search(supplier._get_domain_resupply_mto_leg())
        self.assertTrue(mto_legs)
        self.assertEqual(set(mto_legs.mapped("warehouse_role")), {RESUPPLY_ROLE})


@tagged("post_install", "-at_install")
class TestRuleRoleBackfill(WarehouseRuleRoleCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = load_script(
            f"{get_module_path('stock')}/migrations/1.21/end-migrate_rule_roles.py",
            "stock_1_21_end_migrate_rule_roles",
        )

    def test_backfill_restores_the_generated_roles_and_skips_hand_made_rules(self):
        warehouse = self.warehouse
        supplier = self.env["stock.warehouse"].create(
            {"name": "Backfill Supplier", "code": "BSP"}
        )
        warehouse.write(
            {
                "reception_steps": "three_steps",
                "delivery_steps": "pick_pack_ship",
                "resupply_wh_ids": [Command.link(supplier.id)],
            }
        )
        warehouse.reception_steps = "one_step"
        user_rules = self.add_user_rule(
            warehouse.reception_route_id, warehouse_id=warehouse.id
        ) | self.add_user_rule(warehouse.delivery_route_id)
        rules = self.warehouse_rules(warehouse) | self.warehouse_rules(supplier)
        expected = self.roles_by_rule(rules)
        self.assertTrue(
            any(not rule.active and rule.warehouse_role for rule in rules),
            "the scenario needs an archived, obsolete generated rule",
        )
        self.env.flush_all()
        self.env.cr.execute("UPDATE stock_rule SET warehouse_role = NULL")
        self.env.invalidate_all()

        self.script.migrate(self.env.cr, "1.20")
        self.env.invalidate_all()

        self.assertEqual(self.roles_by_rule(rules), expected)
        self.assertEqual(user_rules.mapped("warehouse_role"), [False, False])

    def test_backfilled_obsolete_rule_is_archived_again_on_reactivation(self):
        warehouse = self.warehouse
        warehouse.reception_steps = "three_steps"
        obsolete = warehouse.reception_route_id.rule_ids.filtered(
            lambda rule: rule.location_dest_id == warehouse.wh_qc_stock_loc_id
        )
        warehouse.reception_steps = "one_step"
        self.assertFalse(obsolete.active)
        self.env.flush_all()
        self.env.cr.execute("UPDATE stock_rule SET warehouse_role = NULL")
        self.env.invalidate_all()

        self.script.migrate(self.env.cr, "1.20")
        self.env.invalidate_all()
        warehouse.action_archive()
        warehouse.action_unarchive()

        self.assertEqual(obsolete.warehouse_role, "reception_route_id")
        self.assertFalse(obsolete.active)
        self.assert_route_follows_steps(warehouse, "reception_route_id")

    def test_fresh_install_is_noop(self):
        self.env.flush_all()
        self.env.cr.execute("UPDATE stock_rule SET warehouse_role = NULL")
        self.script.migrate(self.env.cr, None)
        self.env.cr.execute(
            "SELECT count(*) FROM stock_rule WHERE warehouse_role IS NOT NULL"
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)
