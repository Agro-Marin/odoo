from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestProductionIntegrity(TestMrpCommon):
    def _stock(self, product, quantity, location=None, lot=None):
        self.env["stock.quant"]._update_available_quantity(
            product, location or self.stock_location, quantity, lot_id=lot
        )

    def _batched_manufacture(self, product, quantity):
        reference = self.env["stock.reference"].create({"name": "SO-BATCH"})
        self.env["stock.rule"]._run_manufacture(
            [
                (
                    self.env["stock.rule"].Procurement(
                        product,
                        quantity,
                        product.uom_id,
                        self.warehouse_1.lot_stock_id,
                        "Batch",
                        "Batch",
                        self.warehouse_1.company_id,
                        {
                            "warehouse_id": self.warehouse_1,
                            "date_planned": fields.Datetime.now(),
                            "date_deadline": fields.Datetime.now(),
                            "company_id": self.warehouse_1.company_id,
                            "reference_ids": reference,
                        },
                    ),
                    self.warehouse_1.manufacture_pull_id,
                )
            ]
        )
        return self.env["mrp.production"].search([("product_id", "=", product.id)])

    def _simple_bom(self, finished, component, **values):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_uom_id": finished.uom_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
                **values,
            }
        )

    def test_merged_then_resized_order_produces_its_quantity_once(self):
        mo, _bom, product, _c1, _c2 = self.generate_mo(
            qty_final=30, qty_base_1=1, qty_base_2=1
        )
        productions = mo._split_productions({mo: [10, 10, 10]})
        sibling = productions[2]
        productions[:2].action_merge()
        sibling.move_finished_ids.move_dest_ids = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "location_id": sibling.location_dest_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["change.production.qty"].create(
            {"mo_id": sibling.id, "product_qty": 15}
        ).change_prod_qty()
        self.assertEqual(len(sibling._get_main_finished_moves()), 1)

        sibling.qty_producing = 15
        sibling._update_moves_from_qty_producing()
        sibling.button_mark_done()

        self.assertEqual(sibling.state, "done")
        self.assertEqual(
            sum(sibling._get_main_finished_moves().mapped("quantity")), 15.0
        )
        self.assertEqual(sibling.qty_produced, 15.0)

    def test_an_order_with_a_split_finished_move_produces_its_quantity_once(self):
        mo, *_rest = self.generate_mo(qty_final=15, qty_base_1=1, qty_base_2=1)
        finished = mo._get_main_finished_moves()
        self.env["stock.move"].create(finished._split(5))
        self.assertEqual(len(mo._get_main_finished_moves()), 2)

        mo.qty_producing = 15
        mo._update_moves_from_qty_producing()
        mo.button_mark_done()

        self.assertEqual(mo.state, "done")
        self.assertEqual(sum(mo._get_main_finished_moves().mapped("quantity")), 15.0)
        self.assertEqual(mo.qty_produced, 15.0)

    def test_merge_survives_a_bom_byproduct_removed_from_every_order(self):
        byproduct = self.env["product.product"].create(
            {"name": "Scrap", "is_storable": True}
        )
        finished, component = self.env["product.product"].create(
            [
                {"name": "Merged", "is_storable": True},
                {"name": "Merged part", "is_storable": True},
            ]
        )
        bom = self._simple_bom(
            finished,
            component,
            byproduct_ids=[
                Command.create(
                    {"product_id": byproduct.id, "product_qty": 1, "cost_share": 0}
                )
            ],
        )
        productions = self.env["mrp.production"].create(
            [
                {"product_id": finished.id, "bom_id": bom.id, "product_qty": 2}
                for _index in range(2)
            ]
        )
        productions.action_confirm()
        self.assertEqual(productions.move_byproduct_ids.product_id, byproduct)
        productions.move_byproduct_ids._action_cancel()
        productions.move_byproduct_ids.unlink()

        productions.action_merge()

        merged = (
            self.env["mrp.production"].search([("product_id", "=", finished.id)])
            - productions
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.product_qty, 4)
        self.assertEqual(merged.state, "confirmed")
        self.assertEqual(set(productions.mapped("state")), {"cancel"})

    def _rows(self, production):
        return (
            sorted(production.move_raw_ids.product_id.mapped("name")),
            sorted(production.move_byproduct_ids.product_id.mapped("name")),
            sorted(production.workorder_ids.mapped("name")),
        )

    def _variant_bom(self, template, restriction):
        common, restricted, byproduct = self.env["product.product"].create(
            [
                {"name": "Common part", "is_storable": True},
                {"name": "Restricted part", "is_storable": True},
                {"name": "Restricted scrap", "is_storable": True},
            ]
        )
        restricted_to = [Command.set(restriction.ids)]
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": common.id, "product_qty": 1}),
                    Command.create(
                        {
                            "product_id": restricted.id,
                            "product_qty": 1,
                            "bom_product_template_attribute_value_ids": restricted_to,
                        }
                    ),
                ],
                "byproduct_ids": [
                    Command.create(
                        {
                            "product_id": byproduct.id,
                            "product_qty": 1,
                            "cost_share": 0,
                            "bom_product_template_attribute_value_ids": restricted_to,
                        }
                    )
                ],
                "operation_ids": [
                    Command.create(
                        {"name": "Common step", "workcenter_id": self.workcenter_1.id}
                    ),
                    Command.create(
                        {
                            "name": "Restricted step",
                            "workcenter_id": self.workcenter_1.id,
                            "bom_product_template_attribute_value_ids": restricted_to,
                        }
                    ),
                ],
            }
        )

    def test_update_bom_keeps_the_rows_of_the_orders_no_variant_value(self):
        engrave = self.env["product.attribute"].create(
            {
                "name": "Engrave",
                "create_variant": "no_variant",
                "value_ids": [
                    Command.create({"name": "Yes"}),
                    Command.create({"name": "No"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "Engraved",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": engrave.id,
                            "value_ids": [Command.set(engrave.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        yes = template.attribute_line_ids.product_template_value_ids.filtered(
            lambda value: value.name == "Yes"
        )
        bom = self._variant_bom(template, yes)
        production = self.env["mrp.production"].create(
            {
                "product_id": template.product_variant_id.id,
                "bom_id": bom.id,
                "product_qty": 1,
                "never_product_template_attribute_value_ids": [Command.set(yes.ids)],
            }
        )
        production.action_confirm()
        confirmed = self._rows(production)
        self.assertEqual(
            confirmed,
            (
                ["Common part", "Restricted part"],
                ["Restricted scrap"],
                ["Common step", "Restricted step"],
            ),
        )

        production.action_update_bom()

        self.assertEqual(self._rows(production), confirmed)

    def test_update_bom_applies_a_row_only_on_every_value_it_names(self):
        color, size = self.env["product.attribute"].create(
            [
                {
                    "name": "Color",
                    "value_ids": [
                        Command.create({"name": "Red"}),
                        Command.create({"name": "Blue"}),
                    ],
                },
                {
                    "name": "Size",
                    "value_ids": [
                        Command.create({"name": "S"}),
                        Command.create({"name": "L"}),
                    ],
                },
            ]
        )
        template = self.env["product.template"].create(
            {
                "name": "Shirt",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                    for attribute in (color, size)
                ],
            }
        )
        values = template.attribute_line_ids.product_template_value_ids
        red_large = values.filtered(lambda value: value.name in ("Red", "L"))
        red_small = template.product_variant_ids.filtered(
            lambda variant: (
                set(variant.product_template_attribute_value_ids.mapped("name"))
                == {"Red", "S"}
            )
        )
        bom = self._variant_bom(template, red_large)
        production = self.env["mrp.production"].create(
            {"product_id": red_small.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        confirmed = self._rows(production)
        self.assertEqual(confirmed, (["Common part"], [], ["Common step"]))

        production.action_update_bom()

        self.assertEqual(self._rows(production), confirmed)

    def test_merging_some_siblings_leaves_the_others_moves_in_their_group(self):
        mo, *_rest = self.generate_mo(qty_final=3, qty_base_1=1, qty_base_2=1)
        first, second, third = mo._split_productions({mo: [1, 1, 1]})
        group = third.production_group_id

        merged = self.env["mrp.production"].browse(
            (first | second).action_merge()["res_id"]
        )

        self.assertEqual(third.production_group_id, group)
        self.assertEqual(
            (third.move_raw_ids | third.move_finished_ids).production_group_id, group
        )
        self.assertNotIn(third, merged.production_group_id.move_ids.production_id)

    def test_merging_keeps_the_orders_unit(self):
        dozen = self.env.ref("uom.product_uom_dozen")
        finished, component = self.env["product.product"].create(
            [
                {"name": "Boxed", "is_storable": True, "uom_id": dozen.id},
                {"name": "Box part", "is_storable": True},
            ]
        )
        bom = self._simple_bom(finished, component)
        productions = self.env["mrp.production"].create(
            [
                {
                    "product_id": finished.id,
                    "bom_id": bom.id,
                    "product_qty": 5,
                    "product_uom_id": self.uom_unit.id,
                }
                for _index in range(2)
            ]
        )
        productions.action_confirm()
        demand = sum(productions.move_raw_ids.mapped("product_uom_qty"))

        merged = self.env["mrp.production"].browse(productions.action_merge()["res_id"])

        self.assertEqual(merged.product_uom_id, self.uom_unit)
        self.assertEqual(merged.product_qty, 10)
        self.assertAlmostEqual(
            sum(merged.move_raw_ids.mapped("product_uom_qty")), demand
        )

    def test_batched_orders_from_one_procurement_get_one_pick_each(self):
        self.warehouse_1.manufacture_steps = "pbm"
        finished, component = self.env["product.product"].create(
            [
                {"name": "Batched", "is_storable": True},
                {"name": "Batched component", "is_storable": True},
            ]
        )
        self._simple_bom(finished, component, enable_batch_size=True, batch_size=10.0)

        productions = self._batched_manufacture(finished, 20)

        self.assertEqual(len(productions), 2)
        self.assertEqual(set(productions.mapped("state")), {"confirmed"})
        picks = productions.move_raw_ids.move_orig_ids.picking_id
        self.assertEqual(len(picks), 2)
        for production in productions:
            self.assertEqual(
                production.move_raw_ids.move_orig_ids.picking_id.move_ids.product_uom_qty,
                10,
            )

    def test_reserved_component_counts_as_consumed_on_mark_done(self):
        self.warehouse_1.manufacture_steps = "pbm"
        finished, component = self.env["product.product"].create(
            [
                {"name": "Serial finished", "is_storable": True, "tracking": "serial"},
                {"name": "Serial part", "is_storable": True, "tracking": "serial"},
            ]
        )
        self._simple_bom(finished, component, consumption="warning")
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 1,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        production.action_generate_serial()
        self.assertEqual(production.qty_producing, 1.0)

        part_serial = self.env["stock.lot"].create(
            {"name": "PART-1", "product_id": component.id}
        )
        self._stock(component, 1, lot=part_serial)
        pick = production.picking_ids
        pick.action_assign()
        pick.button_validate()
        self.assertEqual(pick.state, "done")
        self.assertEqual(production.move_raw_ids.quantity, 1.0)

        result = production.button_mark_done()

        self.assertNotIsInstance(result, dict)
        self.assertEqual(production.state, "done")
        self.assertEqual(production.move_raw_ids.lot_ids, part_serial)

    def test_cross_warehouse_order_forecasts_at_its_destination(self):
        other = self.env["stock.warehouse"].create({"name": "Other", "code": "OTH"})
        finished, component = self.env["product.product"].create(
            [
                {"name": "Shipped away", "is_storable": True},
                {"name": "Local part", "is_storable": True},
            ]
        )
        self._simple_bom(finished, component)
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 4,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
                "location_src_id": self.warehouse_1.lot_stock_id.id,
                "location_dest_id": other.lot_stock_id.id,
            }
        )
        production.action_confirm()

        self.assertEqual(
            finished.with_context(location=other.lot_stock_id.id).qty_available_virtual,
            4.0,
        )
        self.assertEqual(
            finished.with_context(
                location=self.warehouse_1.lot_stock_id.id
            ).qty_available_virtual,
            0.0,
        )

    def test_three_step_order_forecasts_in_warehouse_stock(self):
        self.warehouse_1.manufacture_steps = "pbm_sam"
        finished, component = self.env["product.product"].create(
            [
                {"name": "Post-produced", "is_storable": True},
                {"name": "Post part", "is_storable": True},
            ]
        )
        self._simple_bom(finished, component)
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 3,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        self.assertEqual(production.location_dest_id, self.warehouse_1.sam_loc_id)

        self.assertEqual(
            finished.with_context(
                location=self.warehouse_1.lot_stock_id.id
            ).qty_available_virtual,
            3.0,
        )

    def _serial_component_order(self, finished, component, bom):
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        return production

    def _consume_by_hand(self, production, serial):
        move = production.move_raw_ids
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": move.product_id.id,
                "product_uom_id": move.product_uom_id.id,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
                "lot_id": serial.id,
                "quantity": 1,
                "picked": True,
            }
        )
        move.picked = True

    def test_serial_consumed_through_a_hand_made_line_cannot_be_consumed_again(self):
        other_production_location = self.env["stock.location"].create(
            {"name": "Other production", "usage": "production"}
        )
        finished, other_finished, component = self.env["product.product"].create(
            [
                {"name": "Assembly", "is_storable": True},
                {
                    "name": "Other assembly",
                    "is_storable": True,
                    "property_stock_production": other_production_location.id,
                },
                {"name": "Serial board", "is_storable": True, "tracking": "serial"},
            ]
        )
        bom = self._simple_bom(finished, component)
        other_bom = self._simple_bom(other_finished, component)
        serial = self.env["stock.lot"].create(
            {"name": "BOARD-1", "product_id": component.id}
        )

        first = self._serial_component_order(finished, component, bom)
        self._consume_by_hand(first, serial)
        first.qty_producing = 1
        first.button_mark_done()
        self.assertEqual(first.state, "done")
        self._stock(component, 1, lot=serial)

        second = self._serial_component_order(other_finished, component, other_bom)
        self.assertEqual(second.production_location_id, other_production_location)
        self._consume_by_hand(second, serial)
        second.qty_producing = 1
        with self.assertRaisesRegex(UserError, "BOARD-1.*already been consumed"):
            second.button_mark_done()
        self.assertEqual(first.move_raw_ids.move_line_ids.production_id, first)

    def test_update_bom_drops_the_work_order_of_a_deleted_operation(self):
        finished, component = self.env["product.product"].create(
            [
                {"name": "Routed", "is_storable": True},
                {"name": "Routed part", "is_storable": True},
            ]
        )
        bom = self._simple_bom(
            finished,
            component,
            operation_ids=[
                Command.create(
                    {
                        "name": "Cut",
                        "workcenter_id": self.workcenter_1.id,
                        "time_cycle_manual": 10,
                    }
                ),
                Command.create(
                    {
                        "name": "Weld",
                        "workcenter_id": self.workcenter_2.id,
                        "time_cycle_manual": 10,
                    }
                ),
            ],
        )
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        self.assertEqual(production.workorder_ids.mapped("name"), ["Cut", "Weld"])

        bom.operation_ids.filtered(lambda op: op.name == "Weld").unlink()
        production.action_update_bom()

        self.assertEqual(production.workorder_ids.mapped("name"), ["Cut"])

    def test_update_bom_keeps_a_finished_orphan_work_order(self):
        finished, component = self.env["product.product"].create(
            [
                {"name": "Routed done", "is_storable": True},
                {"name": "Routed done part", "is_storable": True},
            ]
        )
        bom = self._simple_bom(
            finished,
            component,
            operation_ids=[
                Command.create({"name": "Cut", "workcenter_id": self.workcenter_2.id}),
                Command.create({"name": "Weld", "workcenter_id": self.workcenter_2.id}),
            ],
        )
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        cut = production.workorder_ids.filtered(lambda wo: wo.name == "Cut")
        cut.button_start()
        cut.button_finish()
        self.assertEqual(cut.state, "done")

        bom.operation_ids.filtered(lambda op: op.name == "Cut").unlink()
        production.action_update_bom()

        self.assertIn(cut, production.workorder_ids)
        self.assertEqual(production.workorder_ids.mapped("name"), ["Cut", "Weld"])

    def test_moves_added_by_hand_carry_the_order_references(self):
        mo, _bom, _product, _c1, _c2 = self.generate_mo()
        extra_component, extra_byproduct = self.env["product.product"].create(
            [
                {"name": "Glue", "is_storable": True},
                {"name": "Offcut", "is_storable": True},
            ]
        )
        mo.move_raw_ids = [
            Command.create(
                {
                    "product_id": extra_component.id,
                    "product_uom_qty": 1,
                    "location_dest_id": self.customer_location.id,
                }
            )
        ]
        mo.move_byproduct_ids = [
            Command.create({"product_id": extra_byproduct.id, "product_uom_qty": 1})
        ]
        raw = mo.move_raw_ids.filtered(lambda m: m.product_id == extra_component)
        byproduct = mo.move_byproduct_ids

        for move in raw | byproduct | mo.move_raw_ids | mo.move_finished_ids:
            self.assertEqual(move.origin, mo._get_origin())
            self.assertEqual(move.production_group_id, mo.production_group_id)
            self.assertEqual(move.reference_ids, mo.reference_ids)
            self.assertEqual(move.propagate_cancel, mo.propagate_cancel)
        self.assertEqual(raw.location_dest_id, mo.production_location_id)
        self.assertEqual(byproduct.location_id, mo.production_location_id)
        self.assertEqual(byproduct.date, mo.date_end)

    def test_deleting_a_done_order_is_refused(self):
        mo, _bom, _product, c1, c2 = self.generate_mo()
        self._stock(c1, 100)
        self._stock(c2, 100)
        mo.action_assign()
        mo.qty_producing = mo.product_qty
        mo._update_moves_from_qty_producing()
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")

        with self.assertRaisesRegex(UserError, "only draft or cancelled"):
            mo.unlink()

        draft = mo.copy()
        draft.unlink()
        self.assertFalse(draft.exists())

    def test_backorders_are_all_reserved_at_mark_done(self):
        productions = self.env["mrp.production"]
        components = self.env["product.product"]
        for _index in range(3):
            mo, _bom, _product, c1, c2 = self.generate_mo(qty_final=4)
            self._stock(c1, 100)
            self._stock(c2, 100)
            productions |= mo
            components |= c1 | c2
        productions.action_assign()
        for production in productions:
            production.qty_producing = 1
            production._update_moves_from_qty_producing()

        action = productions.button_mark_done()
        Form(
            self.env["mrp.production.backorder"].with_context(**action["context"])
        ).save().action_backorder()

        backorders = (
            self.env["mrp.production"].search(
                [("product_id", "in", productions.product_id.ids)]
            )
            - productions
        )
        self.assertEqual(len(backorders), 3)
        self.assertEqual(set(backorders.mapped("reservation_state")), {"assigned"})

    def test_duplicate_serial_inside_one_order_is_refused(self):
        finished, component = self.env["product.product"].create(
            [
                {"name": "Pair", "is_storable": True},
                {"name": "Serial pin", "is_storable": True, "tracking": "serial"},
            ]
        )
        bom = self._simple_bom(finished, component)
        bom.bom_line_ids.product_qty = 2
        serial = self.env["stock.lot"].create(
            {"name": "PIN-1", "product_id": component.id}
        )
        production = self._serial_component_order(finished, component, bom)
        self._consume_by_hand(production, serial)
        self._consume_by_hand(production, serial)
        production.qty_producing = 1

        with self.assertRaisesRegex(UserError, "PIN-1.*already been consumed"):
            production.button_mark_done()

    def test_lot_component_waits_for_its_pre_production_pick(self):
        self.warehouse_1.manufacture_steps = "pbm"
        finished, component = self.env["product.product"].create(
            [
                {"name": "Lot finished", "is_storable": True},
                {"name": "Lot part", "is_storable": True, "tracking": "lot"},
            ]
        )
        self._simple_bom(finished, component, consumption="flexible")
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 1,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        production.qty_producing = 1
        production._update_moves_from_qty_producing()
        self.assertFalse(production.move_raw_ids.move_line_ids.filtered("quantity"))

        lot = self.env["stock.lot"].create(
            {"name": "LOT-A", "product_id": component.id}
        )
        self._stock(component, 1, lot=lot)
        pick = production.picking_ids
        pick.action_assign()
        pick.button_validate()
        self.assertEqual(pick.state, "done")

        self.assertEqual(production.move_raw_ids.move_line_ids.lot_id, lot)
        production.button_mark_done()
        self.assertEqual(production.state, "done")

    def test_second_split_order_generates_its_serial(self):
        finished, component = self.env["product.product"].create(
            [
                {"name": "Split serial", "is_storable": True, "tracking": "serial"},
                {"name": "Split part", "is_storable": True, "tracking": "serial"},
            ]
        )
        bom = self._simple_bom(finished, component)
        self.warehouse_1.manufacture_steps = "pbm"
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "bom_id": bom.id,
                "product_qty": 2,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        serials = self.env["stock.lot"].create(
            [{"name": f"SP-{i}", "product_id": component.id} for i in range(2)]
        )
        for serial in serials:
            self._stock(component, 1, lot=serial)
        pick = production.picking_ids
        pick.action_assign()
        pick.button_validate()
        first, second = production._split_productions({production: [1, 1]})
        first.action_generate_serial()
        first.button_mark_done()
        self.assertEqual(first.state, "done")

        second.action_generate_serial()

        self.assertEqual(second.qty_producing, 1)
        self.assertEqual(second.move_raw_ids.quantity, 1)
        self.assertEqual(len(second.move_raw_ids.lot_ids), 1)
        self.assertNotEqual(second.move_raw_ids.lot_ids, first.move_raw_ids.lot_ids)


@tagged("post_install", "-at_install")
class TestProductionIntegrityForms(TestMrpCommon):
    def test_form_quantity_change_keeps_finished_move_origin(self):
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.bom_1.product_id
        mo_form.bom_id = self.bom_1
        mo_form.product_qty = 2
        production = mo_form.save()
        origin = production._get_origin()
        self.assertEqual(production.move_finished_ids.mapped("origin"), [origin])

        with Form(production) as form:
            form.product_qty = 3
        self.assertEqual(set(production.move_finished_ids.mapped("origin")), {origin})
