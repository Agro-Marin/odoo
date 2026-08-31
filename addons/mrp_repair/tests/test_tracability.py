from odoo.tests import Form, tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestRepairTraceability(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.group_user").write(
            {"implied_ids": [(4, cls.env.ref("stock.group_production_lot").id)]}
        )

    def test_tracking_repair_production(self):
        product_to_repair = self.env["product.product"].create(
            {
                "name": "product first serial to act repair",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        ptrepair_lot = self.env["stock.lot"].create(
            {
                "name": "A1",
                "product_id": product_to_repair.id,
            }
        )
        product_to_remove = self.env["product.product"].create(
            {
                "name": "other first serial to remove with repair",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        ptremove_lot = self.env["stock.lot"].create(
            {
                "name": "B2",
                "product_id": product_to_remove.id,
            }
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": product_to_remove.id,
                "location_id": warehouse.lot_stock_id.id,
                "lot_id": ptremove_lot.id,
                "inventory_quantity": 1,
            }
        )._apply_inventory()

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product_to_repair
        with mo_form.move_raw_ids.new() as move:
            move.product_id = product_to_remove
            move.product_uom_qty = 1
        mo = mo_form.save()
        mo.action_confirm()
        mo.lot_producing_ids = ptrepair_lot
        mo.move_raw_ids.move_line_ids.lot_id = ptremove_lot
        mo.move_raw_ids.picked = True
        mo.button_mark_done()

        with Form(self.env["repair.order"]) as ro_form:
            ro_form.product_id = product_to_repair
            ro_form.lot_id = ptrepair_lot
            with ro_form.move_ids.new() as operation:
                operation.repair_line_type = "remove"
                operation.product_id = product_to_remove
            ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = ptremove_lot
        ro.action_repair_start()
        ro.move_ids.picked = True
        ro.action_repair_end()

        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": product_to_remove.id,
                "location_id": warehouse.lot_stock_id.id,
                "lot_id": ptremove_lot.id,
                "inventory_quantity": 1,
            }
        )._apply_inventory()

        mo2_form = Form(self.env["mrp.production"])
        mo2_form.product_id = product_to_repair
        with mo2_form.move_raw_ids.new() as move:
            move.product_id = product_to_remove
            move.product_uom_qty = 1
        mo2 = mo2_form.save()
        mo2.action_confirm()
        mo2.lot_producing_ids = self.env["stock.lot"].create(
            {
                "name": "A2",
                "product_id": product_to_repair.id,
            }
        )
        mo2.move_raw_ids.move_line_ids.lot_id = ptremove_lot
        mo2.move_raw_ids.picked = True
        mo2.button_mark_done()

    def test_mo_with_used_sn_component(self):

        def produce_one(product, component):
            mo_form = Form(self.env["mrp.production"])
            mo_form.product_id = product
            with mo_form.move_raw_ids.new() as raw_line:
                raw_line.product_id = component
                raw_line.product_uom_qty = 1
            mo = mo_form.save()
            mo.action_confirm()
            mo.action_assign()
            mo.move_raw_ids.picked = True
            mo.button_mark_done()
            return mo

        finished, component = self.env["product.product"].create(
            [
                {
                    "name": "Finished Product",
                    "is_storable": True,
                },
                {
                    "name": "SN Component",
                    "is_storable": True,
                    "tracking": "serial",
                },
            ]
        )

        sn_lot = self.env["stock.lot"].create(
            {
                "product_id": component.id,
                "name": "USN01",
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=sn_lot
        )

        mo = produce_one(finished, component)
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.lot_ids, sn_lot)
        ro_form = Form(self.env["repair.order"])
        ro_form.product_id = finished
        with ro_form.move_ids.new() as ro_line:
            ro_line.repair_line_type = "recycle"
            ro_line.product_id = component
        ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = sn_lot
        ro.action_repair_start()
        ro.move_ids.picked = True
        ro.action_repair_end()
        mo = produce_one(finished, component)
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.lot_ids, sn_lot)
        ro_form = Form(self.env["repair.order"])
        ro_form.product_id = finished
        with ro_form.move_ids.new() as ro_line:
            ro_line.repair_line_type = "recycle"
            ro_line.product_id = component
            ro_line.location_dest_id = self.stock_location
        ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = sn_lot
        ro.action_repair_start()
        ro.action_repair_end()
        self.assertEqual(ro.state, "done")
        ro_form = Form(self.env["repair.order"])
        ro_form.product_id = finished
        with ro_form.move_ids.new() as ro_line:
            ro_line.repair_line_type = "add"
            ro_line.product_id = component
            ro_line.location_id = self.stock_location
        ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = sn_lot
        ro.action_repair_start()
        ro.action_repair_end()
        self.assertEqual(ro.state, "done")
        ro_form = Form(self.env["repair.order"])
        ro_form.product_id = finished
        with ro_form.move_ids.new() as ro_line:
            ro_line.repair_line_type = "recycle"
            ro_line.product_id = component
            ro_line.location_dest_id = self.stock_location
        ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = sn_lot
        ro.action_repair_start()
        ro.action_repair_end()
        self.assertEqual(ro.state, "done")
        mo = produce_one(finished, component)
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.lot_ids, sn_lot)

    def test_mo_with_used_sn_component_02(self):
        finished, component = self.env["product.product"].create(
            [
                {
                    "name": "Finished Product",
                    "is_storable": True,
                },
                {
                    "name": "SN Componentt",
                    "is_storable": True,
                    "tracking": "serial",
                },
            ]
        )

        sn_lot = self.env["stock.lot"].create(
            {
                "product_id": component.id,
                "name": "USN01",
                "company_id": self.env.company.id,
            }
        )

        ro_form = Form(self.env["repair.order"])
        ro_form.product_id = self.product_1
        with ro_form.move_ids.new() as ro_line:
            ro_line.repair_line_type = "remove"
            ro_line.product_id = component
        ro = ro_form.save()
        ro.action_validate()
        ro.move_ids[0].lot_ids = sn_lot
        ro.action_repair_start()
        ro.action_repair_end()

        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=sn_lot
        )
        self.assertEqual(component.qty_available, 1)

        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finished
        with mo_form.move_raw_ids.new() as raw_line:
            raw_line.product_id = component
            raw_line.product_uom_qty = 1
        mo = mo_form.save()
        mo.action_confirm()
        mo.action_assign()
        mo.move_raw_ids.move_line_ids.quantity = 1
        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.lot_ids, sn_lot)
        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.save().action_unbuild()
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = finished
        with mo_form.move_raw_ids.new() as raw_line:
            raw_line.product_id = component
            raw_line.product_uom_qty = 1
        mo = mo_form.save()
        mo.action_confirm()
        mo.action_assign()
        mo.move_raw_ids.move_line_ids.quantity = 1
        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.move_raw_ids.lot_ids, sn_lot)

    def test_mo_with_unscrapped_tracked_component(self):
        scrap_location_id = (
            self.env["stock.location"]
            .search_read(
                [("company_id", "=", self.env.company.id), ("usage", "=", "inventory")],
                fields=["id"],
                limit=1,
            )[0]
            .get("id")
        )

        finished = self.bom_4.product_id
        component = self.bom_4.bom_line_ids.product_id
        component.write(
            {
                "is_storable": True,
                "tracking": "serial",
            }
        )

        sn_lot = self.env["stock.lot"].create(
            {
                "product_id": component.id,
                "name": "SN01",
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 1, lot_id=sn_lot
        )

        mo_form = Form(self.env["mrp.production"])
        mo_form.bom_id = self.bom_4
        mo = mo_form.save()
        mo.action_confirm()
        mo.qty_producing = 1
        mo.move_raw_ids.move_line_ids.quantity = 1
        mo.move_raw_ids.move_line_ids.picked = True
        mo.button_mark_done()

        ro = self.env["repair.order"].create(
            {
                "product_id": finished.id,
                "picking_type_id": self.warehouse_1.repair_type_id.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": component.id,
                            "lot_ids": [(4, sn_lot.id)],
                            "repair_line_type": "remove",
                            "location_dest_id": scrap_location_id,
                            "price_unit": 0,
                        },
                    )
                ],
            }
        )
        ro.action_validate()
        ro.action_repair_start()
        ro.action_repair_end()

        sm = self.env["stock.move"].create(
            {
                "product_id": component.id,
                "product_uom_qty": 1,
                "product_uom_id": component.uom_id.id,
                "location_id": scrap_location_id,
                "location_dest_id": self.stock_location.id,
            }
        )
        sm._action_confirm()
        sm.move_line_ids.write(
            {
                "quantity": 1.0,
                "lot_id": sn_lot.id,
                "picked": True,
            }
        )
        sm._action_done()

        mo_form = Form(self.env["mrp.production"])
        mo_form.bom_id = self.bom_4
        mo = mo_form.save()
        mo.action_confirm()
        mo.qty_producing = 1
        mo.move_raw_ids.move_line_ids.quantity = 1
        mo.move_raw_ids.move_line_ids.picked = True
        mo.button_mark_done()

        self.assertRecordValues(
            mo.move_raw_ids.move_line_ids,
            [
                {
                    "product_id": component.id,
                    "lot_id": sn_lot.id,
                    "quantity": 1.0,
                    "state": "done",
                },
            ],
        )

    def test_repair_with_consumable_kit(self):
        self.assertEqual(self.bom_2.type, "phantom")
        kit_product = self.bom_2.product_id
        kit_product.type = "consu"
        self.assertEqual(kit_product.type, "consu")
        ro = self.env["repair.order"].create(
            {
                "product_id": kit_product.id,
                "picking_type_id": self.warehouse_1.repair_type_id.id,
            }
        )
        ro.action_validate()
        ro.action_repair_start()
        ro.action_repair_end()
        self.assertEqual(ro.state, "done")
