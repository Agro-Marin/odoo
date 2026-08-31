from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpRepairFlow(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.group_user").write(
            {"implied_ids": [(4, cls.env.ref("stock.group_production_lot").id)]}
        )

    def test_repair_with_manufacture_mto_link(self):
        mto_route = self.env.ref("stock.route_warehouse0_mto")
        mto_route.active = True
        manufacturing_route = (
            self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
        )
        rule = mto_route.rule_ids.filtered(
            lambda r: r.picking_type_id.code == "repair_operation"
        )
        rule.procure_method = "make_to_order"

        product = self.env["product.product"].create(
            {
                "name": "Repairable, manufactured",
                "is_storable": True,
                "route_ids": [Command.set([mto_route.id, manufacturing_route.id])],
            }
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": self.product_1.id, "product_qty": 1})
                ],
            }
        )

        repair = self.env["repair.order"].create(
            [
                {
                    "move_ids": [
                        Command.create(
                            {
                                "repair_line_type": "add",
                                "product_id": product.id,
                                "product_uom_qty": 1.0,
                            }
                        )
                    ]
                }
            ]
        )

        repair.action_validate()

        production = repair.reference_ids.production_ids
        self.assertEqual(production.product_id, product)
        self.assertEqual(production.product_qty, 1.0)
        self.assertEqual(production.move_dest_ids.repair_id, repair)
        self.assertEqual(production.repair_count, 1)
        self.assertEqual(repair.production_count, 1)

    def test_adding_kit_parts_to_confirmed_repair(self):
        repair = self.env["repair.order"].create(
            {
                "product_id": self.product.id,
                "picking_type_id": self.warehouse_1.repair_type_id.id,
            }
        )
        repair.action_validate()
        self.assertEqual(repair.state, "confirmed")
        self.assertEqual(len(repair.move_ids), 0)
        self.assertTrue(self.product_5.is_kit)
        self.env["stock.move"].create(
            {
                "repair_id": repair.id,
                "product_id": self.product_5.id,
                "product_uom_qty": 1.0,
                "repair_line_type": "add",
            }
        )
        self.assertEqual(len(repair.move_ids), 2)
        self.assertEqual(
            set(repair.move_ids.product_id.ids),
            set(self.product_5.bom_ids.bom_line_ids.product_id.ids),
        )
