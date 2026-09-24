from odoo import Command
from odoo.tests import tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpActivity(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse_1.manufacture_steps = "pbm"
        cls.final, cls.comp_1, cls.comp_2, raw_1, raw_2 = cls.ProductObj.create(
            [
                {"name": f"Activity {name}", "is_storable": True}
                for name in ("final", "comp 1", "comp 2", "raw 1", "raw 2")
            ]
        )
        mto = cls.warehouse_1.mto_pull_id.route_id
        mto.active = True
        routes = cls.route_manufacture | mto
        for component, raw in ((cls.comp_1, raw_1), (cls.comp_2, raw_2)):
            component.route_ids = [Command.set(routes.ids)]
            cls._bom(component, [raw])
        cls._bom(cls.final, [cls.comp_1, cls.comp_2])

    @classmethod
    def _bom(cls, product, components):
        return cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0})
                    for component in components
                ],
            }
        )

    def _confirmed_chain(self):
        production = self.env["mrp.production"].create(
            {
                "product_id": self.final.id,
                "product_qty": 2.0,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        children = {
            component: self.env["mrp.production"].search(
                [("product_id", "=", component.id), ("state", "=", "confirmed")]
            )
            for component in (self.comp_1, self.comp_2)
        }
        self.assertTrue(all(len(child) == 1 for child in children.values()))
        return production, children

    def test_each_upstream_document_keeps_its_own_walked_moves(self):
        production, children = self._confirmed_chain()
        raw_moves = production.move_raw_ids

        documents = production._get_raw_moves_activity_documents(
            dict.fromkeys(raw_moves, (1.0, 2.0))
        )

        raw_move_of = {move.product_id: move for move in raw_moves}
        for component, child in children.items():
            raw_move = raw_move_of[component]
            [document] = documents[child, child.user_id or self.env.user]
            self.assertEqual(document.changes, {raw_move: (1.0, 2.0)})
            self.assertEqual(document.visited, raw_move.move_orig_ids)

    def test_quantity_exception_names_the_impacted_transfers(self):
        production, children = self._confirmed_chain()
        pick_components = production.move_raw_ids.move_orig_ids.picking_id
        self.assertTrue(pick_components)

        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 1.0}
        ).change_prod_qty()

        for child in children.values():
            [note] = child.activity_ids.mapped("note")
            self.assertEqual(note.count("<li"), 1 + len(pick_components), note)
            self.assertIn("Impacted Transfer(s)", note)
            self.assertIn(pick_components.name, note)
