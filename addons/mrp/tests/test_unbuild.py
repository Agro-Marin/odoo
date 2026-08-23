from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form

from odoo.addons.mrp.tests.common import TestMrpCommon


class TestUnbuild(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.group_user").write(
            {
                "implied_ids": [
                    Command.link(cls.env.ref("stock.group_production_lot").id)
                ],
            }
        )

    def test_unbuild_standart(self):
        mo, bom, p_final, p1, p2 = self.generate_mo()
        self.assertEqual(len(mo), 1, "MO should have been created")

        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 100)
        self.env["stock.quant"]._update_available_quantity(p2, self.stock_location, 5)
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo = mo_form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            0,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 3
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            2,
            "You should have consumed 3 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            92,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            3,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 2
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            0,
            "You should have 0 finalproduct in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            100,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            5,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 5
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, allow_negative=True
            ),
            -5,
            "You should have negative quantity for final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            120,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            10,
            "You should have consumed all the 5 product in stock",
        )

    def test_unbuild_with_final_lot(self):
        mo, bom, p_final, p1, p2 = self.generate_mo(tracking_final="lot")
        self.assertEqual(len(mo), 1, "MO should have been created")

        lot = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": p_final.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 100)
        self.env["stock.quant"]._update_available_quantity(p2, self.stock_location, 5)
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.lot_producing_ids.set(lot)
        mo = mo_form.save()

        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            0,
            "You should have consumed all the 5 product in stock",
        )

        with self.assertRaises(AssertionError):
            x = Form(self.env["mrp.unbuild"])
            x.product_id = p_final
            x.bom_id = bom
            x.product_qty = 3
            x.save()

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 3
        x.lot_id = lot
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot
            ),
            2,
            "You should have consumed 3 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            92,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            3,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 2
        x.lot_id = lot
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot
            ),
            0,
            "You should have 0 finalproduct in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            100,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            5,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.product_qty = 5
        x.lot_id = lot
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot, allow_negative=True
            ),
            -5,
            "You should have negative quantity for final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            120,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            10,
            "You should have consumed all the 5 product in stock",
        )

    def test_unbuild_with_consumed_lot(self):
        mo, bom, p_final, p1, p2 = self.generate_mo(tracking_base_1="lot")
        self.assertEqual(len(mo), 1, "MO should have been created")

        lot = self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": p1.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            p1, self.stock_location, 100, lot_id=lot
        )
        self.env["stock.quant"]._update_available_quantity(p2, self.stock_location, 5)
        mo.action_assign()
        for ml in mo.move_raw_ids.mapped("move_line_ids"):
            if ml.product_id.tracking != "none":
                self.assertEqual(ml.lot_id, lot, "Wrong reserved lot.")

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo = mo_form.save()
        details_operation_form = Form(
            mo.move_raw_ids[1],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.lot_id = lot
            ml.quantity = 20
        details_operation_form.save()

        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot
            ),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            0,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        unbuild_order = x.save()

        with self.assertRaises(UserError):
            unbuild_order.action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            5,
            "You should have consumed 3 final product in stock",
        )

        unbuild_order.mo_id = mo.id
        unbuild_order.product_qty = 3
        unbuild_order.action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            2,
            "You should have consumed 3 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot
            ),
            92,
            "You should have 92 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            3,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.product_qty = 2
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            0,
            "You should have 0 finalproduct in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot
            ),
            100,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            5,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.product_qty = 5
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, allow_negative=True
            ),
            -5,
            "You should have negative quantity for final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot
            ),
            120,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            10,
            "You should have consumed all the 5 product in stock",
        )

    def test_unbuild_with_everything_tracked(self):
        mo, bom, p_final, p1, p2 = self.generate_mo(
            tracking_final="lot", tracking_base_2="lot", tracking_base_1="lot"
        )
        self.assertEqual(len(mo), 1, "MO should have been created")

        lot_final = self.env["stock.lot"].create(
            {
                "name": "lot_final",
                "product_id": p_final.id,
            }
        )
        lot_1 = self.env["stock.lot"].create(
            {
                "name": "lot_consumed_1",
                "product_id": p1.id,
            }
        )
        lot_2 = self.env["stock.lot"].create(
            {
                "name": "lot_consumed_2",
                "product_id": p2.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            p1, self.stock_location, 100, lot_id=lot_1
        )
        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 5, lot_id=lot_2
        )
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo_form.lot_producing_ids.set(lot_final)
        mo = mo_form.save()
        details_operation_form = Form(
            mo.move_raw_ids[0],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 5
        details_operation_form.save()
        details_operation_form = Form(
            mo.move_raw_ids[1],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 20
        details_operation_form.save()

        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot_1
            ),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            0,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        with self.assertRaises(AssertionError):
            x.product_id = p_final
            x.bom_id = bom
            x.product_qty = 3
            x.save()

        with self.assertRaises(AssertionError):
            x.product_id = p_final
            x.bom_id = bom
            x.product_qty = 3
            x.save()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final
            ),
            5,
            "You should have consumed 3 final product in stock",
        )

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final
            ),
            5,
            "You should have consumed 3 final product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.lot_id = lot_final
        x.product_qty = 3
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final
            ),
            2,
            "You should have consumed 3 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot_1
            ),
            92,
            "You should have 92 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            3,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.lot_id = lot_final
        x.product_qty = 2
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final
            ),
            0,
            "You should have 0 finalproduct in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot_1
            ),
            100,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            5,
            "You should have consumed all the 5 product in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.lot_id = lot_final
        x.product_qty = 5
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location, lot_id=lot_final, allow_negative=True
            ),
            -5,
            "You should have negative quantity for final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, lot_id=lot_1
            ),
            120,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            10,
            "You should have consumed all the 5 product in stock",
        )

    def test_unbuild_with_duplicate_move(self):
        mo, bom, p_final, p1, p2 = self.generate_mo(
            tracking_final="none", tracking_base_2="lot", tracking_base_1="none"
        )
        self.assertEqual(len(mo), 1, "MO should have been created")

        lot_1 = self.env["stock.lot"].create(
            {
                "name": "lot_1",
                "product_id": p2.id,
            }
        )
        lot_2 = self.env["stock.lot"].create(
            {
                "name": "lot_2",
                "product_id": p2.id,
            }
        )
        lot_3 = self.env["stock.lot"].create(
            {
                "name": "lot_3",
                "product_id": p2.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 100)
        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 1, lot_id=lot_1
        )
        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 3, lot_id=lot_2
        )
        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 2, lot_id=lot_3
        )
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo = mo_form.save()

        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_1
            ),
            0,
            "You should have consumed all the 1 product for lot 1 in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            0,
            "You should have consumed all the 3 product for lot 2 in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_3
            ),
            1,
            "You should have consumed only 1 product for lot3 in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.bom_id = bom
        x.mo_id = mo
        x.product_qty = 5
        x.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            0,
            "You should have no more final product in stock after unbuild",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            100,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_1
            ),
            1,
            "You should have get your product with lot 1 in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_2
            ),
            3,
            "You should have the 3 basic product for lot 2 in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p2, self.stock_location, lot_id=lot_3
            ),
            2,
            "You should have get one product back for lot 3",
        )

    def test_production_links_with_non_tracked_lots(self):
        mo, _bom, p_final, p1, p2 = self.generate_mo(
            tracking_final="lot", tracking_base_1="none", tracking_base_2="lot"
        )
        lot_1 = self.env["stock.lot"].create(
            {
                "name": "lot_1",
                "product_id": p2.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 3, lot_id=lot_1
        )
        lot_finished_1 = self.env["stock.lot"].create(
            {
                "name": "lot_finished_1",
                "product_id": p_final.id,
            }
        )

        self.assertEqual(mo.product_qty, 5)
        mo_form = Form(mo)
        mo_form.qty_producing = 3.0
        mo_form.lot_producing_ids.set(lot_finished_1)
        mo = mo_form.save()
        self.assertEqual(mo.move_raw_ids[1].quantity, 12)
        details_operation_form = Form(
            mo.move_raw_ids[0],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 3
            ml.lot_id = lot_1
        details_operation_form.save()
        mo.move_raw_ids.picked = True
        Form.from_action(self.env, mo.button_mark_done()).save().action_backorder()

        lot_2 = self.env["stock.lot"].create(
            {
                "name": "lot_2",
                "product_id": p2.id,
            }
        )

        self.env["stock.quant"]._update_available_quantity(
            p2, self.stock_location, 4, lot_id=lot_2
        )
        lot_finished_2 = self.env["stock.lot"].create(
            {
                "name": "lot_finished_2",
                "product_id": p_final.id,
            }
        )

        mo = mo.production_group_id.production_ids[1]
        mo.move_raw_ids.move_line_ids.unlink()
        self.assertEqual(mo.product_qty, 2)
        mo_form = Form(mo)
        mo_form.qty_producing = 2
        mo_form.lot_producing_ids.set(lot_finished_2)
        mo = mo_form.save()
        details_operation_form = Form(
            mo.move_raw_ids[0],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 2
            ml.lot_id = lot_2
        details_operation_form.save()
        mo.button_mark_done()

        mo1 = mo.production_group_id.production_ids[0]
        ml = mo1.finished_move_line_ids[0].consume_line_ids.filtered(
            lambda m: m.product_id == p1 and lot_finished_1 in m.produce_line_ids.lot_id
        )
        self.assertEqual(
            sum(ml.mapped("quantity")),
            12.0,
            "Should have consumed 12 for the first lot",
        )
        ml = mo.finished_move_line_ids[0].consume_line_ids.filtered(
            lambda m: m.product_id == p1 and lot_finished_2 in m.produce_line_ids.lot_id
        )
        self.assertEqual(
            sum(ml.mapped("quantity")), 8.0, "Should have consumed 8 for the second lot"
        )

    def test_unbuild_without_lot_after_tracking_change(self):
        mo, bom, p_final, p1, p2 = self.generate_mo()
        self.assertEqual(len(mo), 1, "MO should have been created")

        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 100)
        self.env["stock.quant"]._update_available_quantity(p2, self.stock_location, 5)
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 5.0
        mo = mo_form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            5,
            "You should have the 5 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            80,
            "You should have 80 products in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            0,
            "You should have consumed all the 5 product in stock",
        )

        p1.tracking = "lot"

        x = Form(self.env["mrp.unbuild"])
        x.product_id = p_final
        x.mo_id = mo
        x.product_qty = 3
        unbuild_order = x.save()
        self.assertEqual(
            unbuild_order.bom_id, bom, "Should have filled bom field automatically"
        )
        unbuild_order.action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            2,
            "You should have consumed 3 final product in stock",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, strict=True
            ),
            92,
            "You should have 92 products in stock without lot",
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p2, self.stock_location),
            3,
            "You should have consumed all the 5 product in stock",
        )

    def test_unbuild_with_routes(self):
        StockQuant = self.env["stock.quant"]
        ProductObj = self.env["product.product"]
        unbuild_location = self.env["stock.location"].create(
            {
                "name": "QC/Unbuild",
                "usage": "internal",
                "location_id": self.warehouse_1.view_location_id.id,
            }
        )

        self.env["stock.route"].create(
            {
                "name": "QC/Unbuild -> Stock",
                "warehouse_selectable": True,
                "warehouse_ids": [Command.link(self.warehouse_1.id)],
                "rule_ids": [
                    Command.create(
                        {
                            "name": "Send Matrial QC/Unbuild -> Stock",
                            "action": "push",
                            "picking_type_id": self.picking_type_int.id,
                            "location_src_id": unbuild_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )

        finshed_product = ProductObj.create(
            {
                "name": "Table",
                "is_storable": True,
            }
        )
        component1 = ProductObj.create(
            {
                "name": "Table head",
                "is_storable": True,
            }
        )
        component2 = ProductObj.create(
            {
                "name": "Table stand",
                "is_storable": True,
            }
        )

        bom = self.env["mrp.bom"].create(
            {
                "product_id": finshed_product.id,
                "product_tmpl_id": finshed_product.product_tmpl_id.id,
                "product_uom_id": self.uom_unit.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component1.id, "product_qty": 1}),
                    Command.create({"product_id": component2.id, "product_qty": 1}),
                ],
            }
        )

        StockQuant._update_available_quantity(component1, self.stock_location, 1)
        StockQuant._update_available_quantity(component2, self.stock_location, 1)

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finshed_product
        mo_form.bom_id = bom
        mo_form.product_uom_id = finshed_product.uom_id
        mo_form.product_qty = 1.0
        mo = mo_form.save()
        self.assertEqual(len(mo), 1, "MO should have been created")
        mo.action_confirm()
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 1.0
        mo_form.save()

        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        self.assertEqual(
            StockQuant._get_available_quantity(finshed_product, self.stock_location),
            1,
            "Table should be available in stock",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component1, self.stock_location),
            0,
            "Table head should not be available in stock",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component2, self.stock_location),
            0,
            "Table stand should not be available in stock",
        )

        x = Form(self.env["mrp.unbuild"])
        x.product_id = finshed_product
        x.bom_id = bom
        x.mo_id = mo
        x.product_qty = 1
        x.location_id = self.stock_location
        x.location_dest_id = unbuild_location
        x.save().action_unbuild()

        self.assertEqual(
            StockQuant._get_available_quantity(finshed_product, self.stock_location),
            0,
            "Table should not be available in stock as it is unbuild",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component1, self.stock_location),
            0,
            "Table head should not be available in stock as it is in QC/Unbuild location",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component2, self.stock_location),
            0,
            "Table stand should not be available in stock as it is in QC/Unbuild location",
        )

        picking = self.env["stock.picking"].search(
            [("product_id", "in", [component1.id, component2.id])]
        )
        self.assertEqual(
            picking.location_id.id,
            unbuild_location.id,
            "Wrong source location in picking",
        )
        self.assertEqual(
            picking.location_dest_id.id,
            self.stock_location.id,
            "Wrong destination location in picking",
        )

        for ml in picking.move_ids:
            ml.write({"quantity": 1, "picked": True})
        picking._action_done()

        self.assertEqual(
            StockQuant._get_available_quantity(finshed_product, self.stock_location),
            0,
            "Table should not be available in stock",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component1, self.stock_location),
            1,
            "Table head should be available in stock as the picking is transferred",
        )
        self.assertEqual(
            StockQuant._get_available_quantity(component2, self.stock_location),
            1,
            "Table stand should be available in stock as the picking is transferred",
        )

    def test_unbuild_decimal_qty(self):
        self.env["decimal.precision"].search([("name", "=", "Product Unit")]).digits = 4

        self.bom_1.product_qty = 3
        self.bom_1.bom_line_ids.product_qty = 5
        self.env["stock.quant"]._update_available_quantity(
            self.product_2, self.stock_location, 3
        )

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.bom_1.product_id
        mo_form.bom_id = self.bom_1
        mo = mo_form.save()
        mo.action_confirm()
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 3
        mo_form.save()
        mo.button_mark_done()

        uo_form = Form(self.env["mrp.unbuild"])
        uo_form.mo_id = mo
        uo_form.product_qty = 1
        uo = uo_form.save()
        uo.action_unbuild()
        self.assertEqual(uo.state, "done")

    def test_unbuild_similar_tracked_components(self):
        compo, finished = self.env["product.product"].create(
            [
                {
                    "name": "compo",
                    "is_storable": True,
                    "tracking": "serial",
                },
                {
                    "name": "finished",
                    "is_storable": True,
                },
            ]
        )

        lot01, lot02 = self.env["stock.lot"].create(
            [
                {
                    "name": n,
                    "product_id": compo.id,
                }
                for n in ["lot01", "lot02"]
            ]
        )
        self.env["stock.quant"]._update_available_quantity(
            compo, self.stock_location, 1, lot_id=lot01
        )
        self.env["stock.quant"]._update_available_quantity(
            compo, self.stock_location, 1, lot_id=lot02
        )

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finished
        with mo_form.move_raw_ids.new() as line:
            line.product_id = compo
            line.product_uom_qty = 1
        with mo_form.move_raw_ids.new() as line:
            line.product_id = compo
            line.product_uom_qty = 1
        mo = mo_form.save()

        mo.action_confirm()
        mo_form = Form(mo)
        mo_form.qty_producing = 1
        mo = mo_form.save()
        mo.action_assign()

        details_operation_form = Form(
            mo.move_raw_ids[0],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 1
        details_operation_form.save()
        details_operation_form = Form(
            mo.move_raw_ids[1],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.edit(0) as ml:
            ml.quantity = 1
        details_operation_form.save()
        mo.move_raw_ids.picked = True
        mo.button_mark_done()

        uo_form = Form(self.env["mrp.unbuild"])
        uo_form.mo_id = mo
        uo_form.product_qty = 1
        uo = uo_form.save()
        uo.action_unbuild()

        self.assertEqual(
            uo.produce_line_ids.filtered(lambda sm: sm.product_id == compo).lot_ids,
            lot01 + lot02,
        )

    def test_unbuild_and_multilocations(self):
        grp_multi_loc = self.env.ref("stock.group_stock_multi_locations")
        self.env.user.write({"group_ids": [Command.link(grp_multi_loc.id)]})
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.user.id)], limit=1
        )
        prod_location = self.env["stock.location"].search(
            [("usage", "=", "production"), ("company_id", "=", self.env.user.id)]
        )
        (
            subloc01,
            subloc02,
        ) = self.stock_location.child_ids[:2]

        mo, _, p_final, p1, p2 = self.generate_mo(
            qty_final=1, qty_base_1=1, qty_base_2=1
        )

        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 1)
        self.env["stock.quant"]._update_available_quantity(p2, self.stock_location, 1)
        mo.action_assign()

        mo_form = Form(mo)
        mo_form.qty_producing = 1.0
        mo = mo_form.save()
        mo.button_mark_done()

        internal_form = Form(self.env["stock.picking"])
        internal_form.picking_type_id = warehouse.int_type_id
        internal_form.location_id = self.stock_location
        internal_form.location_dest_id = subloc01
        with internal_form.move_ids.new() as move:
            move.product_id = p_final
            move.quantity = 1.0
            move.picked = True
        internal_transfer = internal_form.save()
        internal_transfer.button_validate()

        unbuild_order_form = Form(self.env["mrp.unbuild"])
        unbuild_order_form.mo_id = mo
        unbuild_order_form.location_id = subloc01
        unbuild_order_form.location_dest_id = subloc02
        unbuild_order = unbuild_order_form.save()
        unbuild_order.action_unbuild()

        self.assertRecordValues(
            unbuild_order.produce_line_ids,
            [
                {
                    "product_id": p_final.id,
                    "location_id": subloc01.id,
                    "location_dest_id": prod_location.id,
                },
                {
                    "product_id": p2.id,
                    "location_id": prod_location.id,
                    "location_dest_id": subloc02.id,
                },
                {
                    "product_id": p1.id,
                    "location_id": prod_location.id,
                    "location_dest_id": subloc02.id,
                },
            ],
        )

    def test_compute_product_uom_id(self):
        order = self.env["mrp.unbuild"].create(
            {
                "product_id": self.product_4.id,
            }
        )
        self.assertEqual(order.product_uom_id, self.product_4.uom_id)

    def test_compute_location_id(self):
        order = self.env["mrp.unbuild"].create(
            {
                "product_id": self.product_4.id,
            }
        )
        self.assertEqual(order.location_id, self.stock_location)
        self.assertEqual(order.location_dest_id, self.stock_location)

    def test_use_unbuilt_sn_in_mo(self):
        product_1 = self.env["product.product"].create(
            {
                "name": "Product tracked by sn",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        product_1_sn = self.env["stock.lot"].create(
            {
                "name": "sn1",
                "product_id": product_1.id,
            }
        )
        component = self.env["product.product"].create(
            {
                "name": "Product component",
                "is_storable": True,
            }
        )
        bom_1 = self.env["mrp.bom"].create(
            {
                "product_id": product_1.id,
                "product_tmpl_id": product_1.product_tmpl_id.id,
                "product_uom_id": self.env.ref("uom.product_uom_unit").id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1}),
                ],
            }
        )
        product_2 = self.env["product.product"].create(
            {
                "name": "finished Product",
                "is_storable": True,
            }
        )
        self.env["mrp.bom"].create(
            {
                "product_id": product_2.id,
                "product_tmpl_id": product_2.product_tmpl_id.id,
                "product_uom_id": self.env.ref("uom.product_uom_unit").id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": product_1.id, "product_qty": 1}),
                ],
            }
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product_1
        mo_form.bom_id = bom_1
        mo_form.product_qty = 1.0
        mo = mo_form.save()
        mo.action_confirm()

        mo_form = Form(mo)
        mo_form.lot_producing_ids.set(product_1_sn)
        mo = mo_form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.lot_id = product_1_sn
        unbuild_form.save().action_unbuild()

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product_2
        mo2 = mo_form.save()
        mo2.action_confirm()
        details_operation_form = Form(
            mo2.move_raw_ids[0],
            view=self.env.ref("stock.view_stock_move_form_operations"),
        )
        with details_operation_form.move_line_ids.new() as ml:
            ml.lot_id = product_1_sn
            ml.quantity = 1
        details_operation_form.save()
        mo_form = Form(mo2)
        mo_form.qty_producing = 1
        mo2 = mo_form.save()
        mo2.move_raw_ids.picked = True
        mo2.button_mark_done()
        self.assertEqual(mo2.state, "done", "Production order should be in done state.")

    def test_unbuild_mo_with_tracked_product_and_component(self):
        finished_product = self.env["product.product"].create(
            {
                "name": "Product tracked by sn",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        finished_product_sn = self.env["stock.lot"].create(
            {
                "name": "sn1",
                "product_id": finished_product.id,
            }
        )
        component = self.env["product.product"].create(
            {
                "name": "Product component",
                "is_storable": True,
            }
        )
        bom_1 = self.env["mrp.bom"].create(
            {
                "product_id": finished_product.id,
                "product_tmpl_id": finished_product.product_tmpl_id.id,
                "product_uom_id": self.uom_unit.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1}),
                ],
            }
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finished_product
        mo_form.bom_id = bom_1
        mo_form.product_qty = 1.0
        mo = mo_form.save()
        mo.action_confirm()
        mo.lot_producing_ids = finished_product_sn
        mo.move_raw_ids.write({"quantity": 1, "picked": True})
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")
        Form.from_action(self.env, mo.button_unbuild()).save().action_validate()
        self.assertEqual(
            mo.unbuild_ids.produce_line_ids[0].product_id, finished_product
        )
        self.assertEqual(
            mo.unbuild_ids.produce_line_ids[0].lot_ids, finished_product_sn
        )
        self.assertEqual(mo.unbuild_ids.produce_line_ids[1].product_id, component)
        self.assertEqual(mo.unbuild_ids.produce_line_ids[1].lot_ids.id, False)

        component.tracking = "serial"
        component_sn = self.env["stock.lot"].create(
            {
                "name": "component-sn1",
                "product_id": component.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=component_sn
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finished_product
        mo_form.bom_id = bom_1
        mo_form.product_qty = 1.0
        mo_2 = mo_form.save()
        mo_2.action_confirm()
        mo_2.lot_producing_ids = finished_product_sn
        mo_2.move_raw_ids.write({"quantity": 1, "picked": True})
        mo_2.button_mark_done()
        self.assertEqual(
            mo_2.state, "done", "Production order should be in done state."
        )
        action = mo_2.button_unbuild()
        Form.from_action(self.env, action).save().action_validate()
        self.assertEqual(
            mo_2.unbuild_ids.produce_line_ids[0].product_id, finished_product
        )
        self.assertEqual(
            mo_2.unbuild_ids.produce_line_ids[0].lot_ids, finished_product_sn
        )
        self.assertEqual(mo_2.unbuild_ids.produce_line_ids[1].product_id, component)
        self.assertEqual(mo_2.unbuild_ids.produce_line_ids[1].lot_ids, component_sn)

    def test_unbuild_different_qty(self):
        mo_form = Form(self.env["mrp.production"])
        mo_form.bom_id = self.bom_1
        mo = mo_form.save()

        mo.action_confirm()
        mo.move_finished_ids._do_unreserve()
        mo_form = Form(mo)
        mo_form.qty_producing = 4
        mo = mo_form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")
        mo.action_toggle_is_locked()
        with Form(mo) as mo_form:
            mo_form.qty_producing = 10
        self.assertEqual(mo.qty_producing, 10)
        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        self.assertEqual(unbuild_form.product_qty, 10)
        unbuild_form.product_qty = 3
        unbuild_order = unbuild_form.save()
        unbuild_order.action_unbuild()
        self.assertRecordValues(
            unbuild_order.produce_line_ids.move_line_ids,
            [
                {"product_id": self.bom_1.product_id.id, "quantity": 3},
                {
                    "product_id": self.bom_1.bom_line_ids[0].product_id.id,
                    "quantity": 0.6,
                },
                {
                    "product_id": self.bom_1.bom_line_ids[1].product_id.id,
                    "quantity": 1.2,
                },
            ],
        )

    def test_unbuild_less_quantity_consumed(self):
        bom = self.env["mrp.bom"].create(
            {
                "product_id": self.product_2.id,
                "product_tmpl_id": self.product_2.product_tmpl_id.id,
                "consumption": "flexible",
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create(
                        {"product_id": self.product_3.id, "product_qty": 20}
                    ),
                ],
            }
        )

        with Form(self.env["mrp.production"]) as mo_form:
            mo_form.product_id = self.product_2
            mo_form.bom_id = bom
            mo_form.product_qty = 1
            mo = mo_form.save()
        mo.action_confirm()

        mo.qty_producing = 1.0
        mo.move_raw_ids.write({"quantity": 15, "picked": True})
        mo.button_mark_done()

        Form.from_action(self.env, mo.button_unbuild()).save().action_validate()
        self.assertEqual(
            mo.unbuild_ids.produce_line_ids.filtered(
                lambda m: m.product_id == self.product_3
            ).product_uom_qty,
            15,
        )

    def test_unbuild_mo_different_qty(self):
        bom = self.env["mrp.bom"].create(
            {
                "product_id": self.product_2.id,
                "product_tmpl_id": self.product_2.product_tmpl_id.id,
                "consumption": "flexible",
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": self.product_3.id, "product_qty": 1})
                ],
            }
        )

        with Form(self.env["mrp.production"]) as mo_form:
            mo_form.product_id = self.product_2
            mo_form.bom_id = bom
            mo_form.product_qty = 10
            mo = mo_form.save()
        mo.action_confirm()

        mo.qty_producing = 12
        mo.move_raw_ids.write({"quantity": 12, "picked": True})
        mo.button_mark_done()

        unbuild_action = mo.button_unbuild()
        unbuild_action["context"]["default_product_qty"] = 12
        Form.from_action(self.env, unbuild_action).save().action_validate()

        unbuild_fns_move = mo.unbuild_ids.produce_line_ids.filtered(
            lambda m: m.product_id == self.product_2
        )
        self.assertEqual(len(unbuild_fns_move), 1)
        self.assertEqual(unbuild_fns_move.state, "done")
        self.assertEqual(unbuild_fns_move.quantity, 12)

    def test_putaway_strategy_with_unbuild(self):
        putaway_strategy = self.env["stock.putaway.rule"].create(
            {
                "location_in_id": self.stock_location.id,
                "location_out_id": self.shelf_1.id,
                "product_id": self.bom_4.bom_line_ids.product_id.id,
            }
        )
        mo = self.env["mrp.production"].create(
            {
                "product_id": self.bom_4.product_id.id,
                "product_qty": 1.0,
                "bom_id": self.bom_4.id,
                "product_uom_id": self.bom_4.product_uom_id.id,
            }
        )
        mo.action_confirm()
        mo.qty_producing = 1.0
        mo.move_raw_ids.write({"quantity": 1, "picked": True})
        mo.button_mark_done()

        unbuild_action = mo.button_unbuild()
        unbuild_action["context"]["default_product_qty"] = 1
        unbuild_order = Form.from_action(self.env, unbuild_action).save()
        unbuild_order.action_unbuild()

        component_move_unbuild = unbuild_order.produce_line_ids.filtered(
            lambda m: m.product_id == self.bom_4.bom_line_ids.product_id
        )
        self.assertEqual(
            component_move_unbuild.move_line_ids.location_dest_id,
            putaway_strategy.location_out_id,
        )

    def test_unbuild_consigned_comp(self):
        consigned_partner = self.env["res.partner"].create(
            {"name": "consigned partner"}
        )
        mo, _, _, p1, _ = self.generate_mo(qty_final=1, qty_base_1=7)
        self.assertEqual(len(mo), 1, "MO should have been created")
        self.env["stock.quant"]._update_available_quantity(p1, self.stock_location, 3)
        self.env["stock.quant"]._update_available_quantity(
            p1, self.stock_location, 4, owner_id=consigned_partner
        )

        mo.action_assign()
        mo_form = Form(mo)
        mo_form.qty_producing = 1
        mo = mo_form.save()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done", "Production order should be in done state.")

        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.save().action_unbuild()

        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location), 7
        )
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p1, self.stock_location, owner_id=consigned_partner
            ),
            4,
        )

    def test_unbuild_non_storable_product(self):
        self.product_4.is_storable = False
        self.product_3.is_storable = False

        self.env["mrp.bom.byproduct"].create(
            {
                "bom_id": self.bom_1.id,
                "product_id": self.product_3.id,
                "product_qty": 1,
                "product_uom_id": self.product_3.uom_id.id,
            }
        )

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.product_4
        mo_form.bom_id = self.bom_1
        mo_form.product_uom_id = self.product_4.uom_id
        mo_form.product_qty = 4.0
        mo = mo_form.save()
        mo.action_confirm()

        mo_form = Form(mo)
        mo_form.qty_producing = 4.0
        mo_form.save()

        mo.button_mark_done()

        unbuild_wizard = Form(self.env["mrp.unbuild"])
        unbuild_wizard.mo_id = mo
        unbuild = unbuild_wizard.save()
        unbuild.action_unbuild()

        self.assertRecordValues(
            unbuild.produce_line_ids,
            [
                {
                    "product_id": self.product_4.id,
                    "quantity": 4,
                    "state": "done",
                },
                {
                    "product_id": self.product_3.id,
                    "quantity": 12,
                    "state": "done",
                },
                {
                    "product_id": self.product_2.id,
                    "quantity": 24,
                    "state": "done",
                },
                {
                    "product_id": self.product_1.id,
                    "quantity": 48,
                    "state": "done",
                },
            ],
        )

    def test_unbuild_tracked_component_multiple_unbuilds_same_mo(self):
        (self.bom_4.product_id | self.bom_4.bom_line_ids.product_id).is_storable = True
        (self.bom_4.product_id | self.bom_4.bom_line_ids.product_id).tracking = "serial"
        component = self.bom_4.bom_line_ids.product_id
        sn1 = self.env["stock.lot"].create(
            {
                "name": "SN1",
                "product_id": component.id,
            }
        )
        sn2 = self.env["stock.lot"].create(
            {
                "name": "SN2",
                "product_id": component.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=sn1
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=sn2
        )
        fp_sn1 = self.env["stock.lot"].create(
            {
                "name": "SN1-P1",
                "product_id": self.bom_4.product_id.id,
            }
        )
        fp_sn2 = self.env["stock.lot"].create(
            {
                "name": "SN2-P1",
                "product_id": self.bom_4.product_id.id,
            }
        )
        mo = self.env["mrp.production"].create(
            {
                "product_id": self.bom_4.product_id.id,
                "product_qty": 2.0,
                "bom_id": self.bom_4.id,
                "product_uom_id": self.bom_4.product_uom_id.id,
            }
        )
        mo.action_confirm()
        mo.lot_producing_ids = fp_sn1 + fp_sn2
        mo._inverse_qty_producing()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.move_line_ids.lot_id, sn1 + sn2)

        unbuild_1 = self.env["mrp.unbuild"].create(
            {
                "mo_id": mo.id,
                "product_id": self.bom_4.product_id.id,
                "lot_id": fp_sn1.id,
            }
        )
        unbuild_1.action_unbuild()
        self.assertEqual(unbuild_1.state, "done")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                component, self.stock_location, lot_id=sn1
            ),
            1,
            "SN1 should be restored after first unbuild",
        )
        unbuild_2 = self.env["mrp.unbuild"].create(
            {
                "mo_id": mo.id,
                "product_id": self.bom_4.product_id.id,
                "lot_id": fp_sn2.id,
            }
        )
        unbuild_2.action_unbuild()
        self.assertEqual(unbuild_2.state, "done")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                component, self.stock_location, lot_id=sn2
            ),
            1,
            "SN2 should be restored after second unbuild",
        )
