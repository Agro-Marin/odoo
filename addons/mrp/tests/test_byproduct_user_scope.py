from odoo import Command
from odoo.tests import TransactionCase

from odoo.addons.mail.tests.common import mail_new_test_user


class TestByproductUserScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref("stock.warehouse0")
        cls.warehouse.manufacture_steps = "pbm_sam"
        cls.finished, cls.component, cls.byproduct = cls.env["product.product"].create(
            [
                {"name": "Scope Finished", "is_storable": True},
                {"name": "Scope Component", "is_storable": True},
                {"name": "Scope By-product", "is_storable": True},
            ]
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
                "byproduct_ids": [
                    Command.create({"product_id": cls.byproduct.id, "product_qty": 2})
                ],
            }
        )
        cls.user = mail_new_test_user(
            cls.env,
            name="Scope MRP User",
            login="scope_mrp_user",
            groups="mrp.group_mrp_user,stock.group_stock_user,mrp.group_mrp_byproducts",
        )

    def _create_as_form_saves(self):
        return (
            self.env["mrp.production"]
            .with_user(self.user)
            .create(
                {
                    "product_id": self.finished.id,
                    "product_qty": 1,
                    "picking_type_id": self.warehouse.manu_type_id.id,
                    "move_raw_ids": [
                        Command.create(
                            {
                                "bom_line_id": self.bom.bom_line_ids.id,
                                "product_id": self.component.id,
                                "product_uom_qty": 1,
                            }
                        )
                    ],
                    "move_byproduct_ids": [
                        Command.create(
                            {"product_id": self.byproduct.id, "product_uom_qty": 2}
                        )
                    ],
                }
            )
        )

    def test_a_user_created_order_keeps_the_byproduct_move_it_was_given(self):
        production = self._create_as_form_saves()

        byproduct_moves = production.move_finished_ids.filtered(
            lambda move: move.product_id == self.byproduct
        )
        self.assertEqual(byproduct_moves.mapped("product_uom_qty"), [2])
        self.assertEqual(production.move_byproduct_ids, byproduct_moves)

    def test_store_finished_product_carries_the_product_and_its_byproduct(self):
        production = self._create_as_form_saves()
        production.action_confirm()
        production.button_mark_done()

        self.assertEqual(production.state, "done")
        store = production.picking_ids.filtered(
            lambda picking: picking.picking_type_id == self.warehouse.sam_type_id
        )
        self.assertEqual(
            {(move.product_id, move.product_qty) for move in store.move_ids},
            {(self.finished, 1), (self.byproduct, 2)},
        )
