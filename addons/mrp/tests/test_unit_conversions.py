from odoo import Command
from odoo.tests import Form, tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestBomBatchFactor(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_gram = cls.env.ref("uom.product_uom_gram")
        cls.uom_kgm = cls.env.ref("uom.product_uom_kgm")
        cls.finished, cls.component, cls.byproduct = cls.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Component", "is_storable": True},
                {"name": "Byproduct", "is_storable": True},
            ]
        )

    def _dozen_bom(self, product, bom_type="normal"):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_uom_id": self.uom_dozen.id,
                "product_qty": 1,
                "type": bom_type,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 12})
                ],
            }
        )

    def test_the_factor_is_not_rounded(self):
        bom = self._dozen_bom(self.finished)
        self.assertAlmostEqual(bom._get_explode_factor(1, self.uom_unit), 1 / 12)

    def test_a_kit_is_available_in_its_own_unit(self):
        kit = self.env["product.product"].create({"name": "Kit"})
        self._dozen_bom(kit, bom_type="phantom")
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 24
        )
        self.assertEqual(kit.qty_available, 24)

    def test_a_kit_delivery_ships_what_one_kit_holds(self):
        kit = self.env["product.product"].create({"name": "Kit"})
        self._dozen_bom(kit, bom_type="phantom")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": kit.id,
                            "product_uom_qty": 1,
                            "product_uom_id": self.uom_unit.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        self.assertEqual(picking.move_ids.product_id, self.component)
        self.assertEqual(picking.move_ids.product_uom_qty, 1.0)

    def test_a_byproduct_scales_with_the_unrounded_factor(self):
        (self.finished | self.component | self.byproduct).uom_id = self.uom_gram
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "product_uom_id": self.uom_kgm.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create(
                        {
                            "product_id": self.component.id,
                            "product_qty": 1000,
                            "product_uom_id": self.uom_gram.id,
                        }
                    )
                ],
                "byproduct_ids": [
                    Command.create(
                        {
                            "product_id": self.byproduct.id,
                            "product_qty": 100,
                            "product_uom_id": self.uom_gram.id,
                        }
                    )
                ],
            }
        )
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = bom
        form.product_uom_id = self.uom_gram
        form.product_qty = 5
        production = form.save()
        self.assertEqual(production.move_raw_ids.product_uom_qty, 5.0)
        self.assertEqual(production.move_byproduct_ids.product_uom_qty, 0.5)

    def test_an_unbuild_without_order_returns_what_one_unit_holds(self):
        bom = self._dozen_bom(self.finished)
        self.env["stock.quant"]._update_available_quantity(
            self.finished, self.stock_location, 5
        )
        unbuild = self.env["mrp.unbuild"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 1,
                "product_uom_id": self.uom_unit.id,
            }
        )
        unbuild.action_unbuild()
        returned = unbuild.produce_line_ids.filtered(
            lambda move: move.product_id == self.component
        )
        self.assertEqual(sum(returned.mapped("quantity")), 1.0)

    def test_the_split_batch_size_is_read_in_the_bom_unit(self):
        bom = self._dozen_bom(self.finished)
        bom.write({"enable_batch_size": True, "batch_size": 2})
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = bom
        form.product_uom_id = self.uom_unit
        form.product_qty = 48
        production = form.save()
        production.action_confirm()
        wizard = self.env["mrp.production.split"].create(
            {"production_id": production.id}
        )
        self.assertEqual(wizard.max_batch_size, 24)
        self.assertEqual(wizard.num_splits, 2)

    def test_the_forecast_counts_draft_orders_in_the_product_unit(self):
        bom = self._dozen_bom(self.finished)
        self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 2,
                "product_uom_id": self.uom_dozen.id,
            }
        )
        locations = self.warehouse_1.view_location_id.child_internal_location_ids
        header = self.env["stock.forecasted_product_product"]._get_report_header(
            False, self.finished.ids, locations.ids
        )
        self.assertEqual(
            header["product"][self.finished.id]["draft_production_qty"]["in"], 24
        )

    def _produced_in_units(self, qty):
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 1})
                ],
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": bom.id, "product_qty": qty}
        )
        production.action_confirm()
        production.action_assign()
        production.qty_producing = qty
        production.move_raw_ids.picked = True
        production.button_mark_done()
        return bom, production

    def test_an_unbuild_in_another_unit_returns_its_share_of_the_order(self):
        _bom, production = self._produced_in_units(10)
        unbuild = self.env["mrp.unbuild"].create(
            {
                "mo_id": production.id,
                "product_qty": 0.5,
                "product_uom_id": self.uom_dozen.id,
            }
        )
        unbuild.action_unbuild()
        returned = unbuild.produce_line_ids.filtered(
            lambda move: move.product_id == self.component
        )
        self.assertEqual(sum(returned.mapped("quantity")), 6)

    def test_a_capacity_in_another_unit_keeps_every_cycle(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Per unit", "time_start": 0, "time_stop": 0}
        )
        self.env["mrp.workcenter.capacity"].create(
            {
                "workcenter_id": workcenter.id,
                "product_id": self.finished.id,
                "product_uom_id": self.uom_unit.id,
                "capacity": 1,
            }
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": "one a minute",
                            "workcenter_id": workcenter.id,
                            "time_cycle_manual": 1,
                        }
                    )
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 2,
                "product_uom_id": self.uom_dozen.id,
            }
        )
        production.action_confirm()
        self.assertEqual(production.workorder_ids.duration_expected, 24)

    def test_a_line_added_after_confirmation_is_scaled_exactly(self):
        self.finished.uom_id = self.uom_dozen
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "product_uom_id": self.uom_unit.id,
                "product_qty": 4,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 2})
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 5,
                "product_uom_id": self.uom_unit.id,
            }
        )
        production.action_confirm()
        self.assertEqual(production.move_raw_ids.product_uom_qty, 2.5)
        bom.bom_line_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 2})
        ]
        production.action_update_bom()
        added = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.byproduct
        )
        self.assertEqual(added.product_uom_qty, 2.5)
        self.assertEqual(
            production.move_raw_ids.filtered(
                lambda move: move.product_id == self.component
            ).product_uom_qty,
            2.5,
        )
