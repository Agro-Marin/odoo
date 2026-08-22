from odoo.exceptions import UserError
from odoo.tests import Form

from odoo.addons.mrp.tests.common import TestMrpCommon


class TestMrpCancelMO(TestMrpCommon):
    def test_cancel_mo_without_routing_1(self):
        manufacturing_order = self.generate_mo()[0]
        manufacturing_order.action_cancel()
        self.assertEqual(
            manufacturing_order.state, "cancel", "MO should be in cancel state."
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[0].state,
            "cancel",
            "Cancelled MO raw moves must be cancelled as well.",
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[1].state,
            "cancel",
            "Cancelled MO raw moves must be cancelled as well.",
        )
        self.assertEqual(
            manufacturing_order.move_finished_ids.state,
            "cancel",
            "Cancelled MO finished move must be cancelled as well.",
        )

    def test_cancel_mo_without_routing_2(self):
        manufacturing_order = self.generate_mo()[0]
        mo_form = Form(manufacturing_order)
        mo_form.qty_producing = 2
        manufacturing_order = mo_form.save()
        manufacturing_order.action_cancel()
        self.assertEqual(
            manufacturing_order.state, "cancel", "MO should be in cancel state."
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[0].state,
            "cancel",
            "Cancelled MO raw moves must be cancelled as well.",
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[1].state,
            "cancel",
            "Cancelled MO raw moves must be cancelled as well.",
        )
        self.assertEqual(
            manufacturing_order.move_finished_ids.state,
            "cancel",
            "Cancelled MO finished move must be cancelled as well.",
        )

    def test_cancel_mo_without_routing_3(self):
        manufacturing_order = self.generate_mo(consumption="strict")[0]
        mo_form = Form(manufacturing_order)
        mo_form.qty_producing = 2
        manufacturing_order = mo_form.save()
        manufacturing_order._post_inventory()
        manufacturing_order.action_cancel()
        self.assertEqual(
            manufacturing_order.state, "done", "MO should be in done state."
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[0].state,
            "done",
            "Due to 'post_inventory', some move raw must stay in done state",
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[1].state,
            "done",
            "Due to 'post_inventory', some move raw must stay in done state",
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[2].state,
            "cancel",
            "The other move raw are cancelled like their MO.",
        )
        self.assertEqual(
            manufacturing_order.move_raw_ids[3].state,
            "cancel",
            "The other move raw are cancelled like their MO.",
        )
        self.assertEqual(
            manufacturing_order.move_finished_ids[0].state,
            "done",
            "Due to 'post_inventory', a move finished must stay in done state",
        )
        self.assertEqual(
            manufacturing_order.move_finished_ids[1].state,
            "cancel",
            "The other move finished is cancelled like its MO.",
        )

    def test_unlink_mo(self):
        manufacturing_order = self.generate_mo()[0]
        self.assertEqual(manufacturing_order.exists().state, "confirmed")
        manufacturing_order.unlink()
        self.assertEqual(manufacturing_order.exists().state, False)

        manufacturing_order = self.generate_mo()[0]
        mo_form = Form(manufacturing_order)
        mo_form.qty_producing = 2
        manufacturing_order = mo_form.save()
        manufacturing_order._post_inventory()
        self.assertEqual(manufacturing_order.exists().state, "progress")
        with self.assertRaises(UserError):
            manufacturing_order.unlink()

    def test_cancel_mo_without_component(self):
        product_form = Form(self.env["product.product"])
        product_form.name = "SuperProduct"
        product = product_form.save()

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo = mo_form.save()

        mo.action_confirm()
        mo.action_cancel()

        self.assertEqual(mo.move_finished_ids.state, "cancel")
        self.assertEqual(mo.state, "cancel")

    def test_cannot_cancel_done_mo_with_three_steps(self):
        self.warehouse_1.manufacture_steps = "pbm_sam"
        mo = self.env["mrp.production"].create(
            {
                "bom_id": self.bom_1.id,
            }
        )
        mo.action_confirm()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        with self.assertRaises(UserError):
            mo.action_cancel()
        self.assertNotEqual(mo.picking_ids.mapped("state"), ["cancel", "cancel"])
        with self.assertRaises(UserError):
            mo.unlink()
