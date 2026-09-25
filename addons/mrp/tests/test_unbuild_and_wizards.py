import gc
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestUnbuildAndWizards(TestMrpCommon):
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

    def _produce(self, mo, qty=None, lot=None):
        mo.action_assign()
        mo_form = Form(mo)
        mo_form.qty_producing = qty or mo.product_qty
        if lot:
            mo_form.lot_producing_ids.set(lot)
        mo = mo_form.save()
        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        return mo

    def _stock(self, product, qty, lot=None):
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot
        )

    def test_unbuild_default_quantity_is_what_remains(self):
        mo, _bom, p_final, p1, p2 = self.generate_mo()
        self._stock(p1, 100)
        self._stock(p2, 5)
        self._produce(mo)

        first = Form(self.env["mrp.unbuild"])
        first.mo_id = mo
        self.assertEqual(first.product_qty, 5)
        first.product_qty = 3
        first.save().action_unbuild()

        second = Form(self.env["mrp.unbuild"])
        second.mo_id = mo
        self.assertEqual(second.product_qty, 2)
        second.save().action_unbuild()
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            0,
        )

    def test_unbuilding_more_than_was_produced_is_refused(self):
        mo, _bom, p_final, p1, p2 = self.generate_mo()
        self._stock(p1, 100)
        self._stock(p2, 5)
        self._produce(mo)
        self.env["mrp.unbuild"].create(
            {"mo_id": mo.id, "product_qty": 3}
        ).action_unbuild()
        too_many = self.env["mrp.unbuild"].create({"mo_id": mo.id, "product_qty": 3})
        with self.assertRaisesRegex(UserError, "at most 2"):
            too_many.action_unbuild()
        self.assertEqual(too_many.state, "draft")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                p_final, self.stock_location
            ),
            2,
        )

    def test_the_unbuild_limit_is_read_in_the_order_unit(self):
        mo, _bom, _p_final, p1, p2 = self.generate_mo(qty_final=12)
        self._stock(p1, 100)
        self._stock(p2, 20)
        self._produce(mo)
        self.env["mrp.unbuild"].create(
            {"mo_id": mo.id, "product_qty": 1, "product_uom_id": self.uom_dozen.id}
        ).action_unbuild()
        with self.assertRaises(UserError):
            self.env["mrp.unbuild"].create(
                {"mo_id": mo.id, "product_qty": 1, "product_uom_id": self.uom_unit.id}
            ).action_unbuild()

    def test_unbuild_links_the_unbuilt_lot_to_the_released_components(self):
        mo, _bom, p_final, p1, p2 = self.generate_mo(
            tracking_final="lot", tracking_base_1="lot"
        )
        final_lot, component_lot = self.env["stock.lot"].create(
            [
                {"name": "FIN", "product_id": p_final.id},
                {"name": "CMP", "product_id": p1.id},
            ]
        )
        self._stock(p1, 30, lot=component_lot)
        self._stock(p2, 5)

        delivery = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "partner_id": self.partner_1.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": p1.id,
                            "product_uom_qty": 10,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        delivery.action_confirm()
        delivery.action_assign()
        delivery.move_ids.picked = True
        delivery.button_validate()
        self.assertEqual(delivery.state, "done")

        self._produce(mo, lot=final_lot)

        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.lot_id = final_lot
        unbuild = unbuild_form.save()
        unbuild.action_unbuild()

        unbuilt_line = unbuild.produce_line_ids.filtered(
            lambda m: m.product_id == p_final
        ).move_line_ids
        released_line = unbuild.produce_line_ids.filtered(
            lambda m: m.product_id == p1
        ).move_line_ids
        self.assertEqual(unbuilt_line.lot_id, final_lot)
        self.assertEqual(released_line.lot_id, component_lot)
        self.assertEqual(released_line.consume_line_ids, unbuilt_line)
        self.assertEqual(
            self.env["stock.traceability.report"]._get_linked_move_lines(released_line)[
                1
            ],
            unbuilt_line,
        )
        final_lot.invalidate_recordset(["delivery_ids"])
        self.assertFalse(final_lot.delivery_ids)

    def test_serial_split_replaces_the_serials_of_the_first_order(self):
        product = self.env["product.product"].create(
            {"name": "Serial Box", "is_storable": True, "tracking": "serial"}
        )
        component = self.env["product.product"].create(
            {"name": "Serial Box Part", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo_form.bom_id = bom
        mo_form.product_qty = 3
        mo = mo_form.save()
        mo.action_confirm()
        old_serial = self.env["stock.lot"].create(
            {"name": "S0", "product_id": product.id}
        )
        mo.lot_producing_ids = old_serial

        wizard = self.env["mrp.production.serials"].create(
            {"production_id": mo.id, "serial_numbers": "A\nB\nC"}
        )
        wizard.action_split_and_assign_serials()

        orders = mo.production_group_id.production_ids
        self.assertEqual(len(orders), 3)
        self.assertEqual(mo.lot_producing_ids.mapped("name"), ["A"])
        self.assertEqual(
            sorted(orders.lot_producing_ids.mapped("name")), ["A", "B", "C"]
        )

    def test_consumption_warning_sets_the_live_move_not_a_cancelled_one(self):
        mo, _bom, _p_final, p1, p2 = self.generate_mo(consumption="warning")
        self._stock(p1, 100)
        self._stock(p2, 5)
        original = mo.move_raw_ids.filtered(lambda m: m.product_id == p1)
        original._action_cancel()
        mo.move_raw_ids = [
            Command.create(
                {
                    "product_id": p1.id,
                    "product_uom_qty": 20,
                    "location_id": mo.location_src_id.id,
                    "location_dest_id": mo.production_location_id.id,
                }
            )
        ]
        live = mo.move_raw_ids.filtered(
            lambda m: m.product_id == p1 and m.state != "cancel"
        )
        live._action_confirm()
        self.assertEqual(original.state, "cancel")
        self.assertEqual(
            mo.move_raw_ids.filtered(lambda m: m.product_id == p1)[0], original
        )

        mo.action_assign()
        mo.qty_producing = 5
        live.quantity = 25
        mo.move_raw_ids.picked = True
        action = mo.button_mark_done()
        self.assertEqual(action.get("res_model"), "mrp.consumption.warning")
        warning = Form.from_action(self.env, action).save()
        warning.action_set_qty()

        self.assertEqual(mo.state, "done")
        self.assertEqual(live.quantity, 20)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(p1, self.stock_location),
            80,
        )

    def _workorder_bom(self, operations):
        component, lone = self.env["product.product"].create(
            [
                {"name": "Operated Part", "is_storable": True},
                {"name": "Lone Part", "is_storable": True},
            ]
        )
        product = self.env["product.product"].create(
            {"name": "Operated Box", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "operation_ids": [
                    Command.create(
                        {
                            "name": f"Step {index}",
                            "workcenter_id": self.workcenter_1.id,
                            "time_cycle": 10,
                            "sequence": index,
                        }
                    )
                    for index in range(operations)
                ],
            }
        )
        bom.bom_line_ids = [
            Command.create(
                {
                    "product_id": component.id,
                    "product_qty": 1,
                    "operation_id": bom.operation_ids[0].id,
                }
            ),
            Command.create({"product_id": lone.id, "product_qty": 1}),
        ]
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo_form.bom_id = bom
        mo_form.product_qty = 4
        mo = mo_form.save()
        mo.action_confirm()
        return mo, component, lone

    def test_quantity_change_keeps_done_lines_on_their_workorder(self):
        mo, _component, lone = self._workorder_bom(2)
        first_wo = mo.workorder_ids[0]
        self._stock(lone, 10)
        lone_move = mo.move_raw_ids.filtered(lambda m: m.product_id == lone)
        self.assertFalse(lone_move.workorder_id)
        lone_move._action_assign()
        lone_move.move_line_ids.workorder_id = first_wo
        lone_move.picked = True
        lone_move._action_done()
        self.assertEqual(lone_move.state, "done")

        self.env["change.production.qty"].create(
            {"mo_id": mo.id, "product_qty": 6}
        ).change_prod_qty()

        self.assertEqual(mo.product_qty, 6)
        self.assertEqual(lone_move.move_line_ids.workorder_id, first_wo)
        self.assertFalse(lone_move.workorder_id)

    def test_quantity_change_statements_per_workorder_are_bounded(self):
        counts = []
        for operations in (2, 8):
            mo, _component, _lone = self._workorder_bom(operations)
            wizard = self.env["change.production.qty"].create(
                {"mo_id": mo.id, "product_qty": 6}
            )
            self.env.flush_all()
            self.env.invalidate_all()
            self.env.registry.clear_all_caches()
            gc.collect()
            before = self.env.cr.sql_statement_count
            wizard.change_prod_qty()
            self.env.flush_all()
            counts.append(self.env.cr.sql_statement_count - before)
        self.assertLessEqual(counts[1] - counts[0], (8 - 2) * 10, counts)

    def test_replenishment_info_lists_only_boms_the_orderpoint_can_use(self):
        variant, other_variant = self.product_7_1, self.product_7_2
        (variant | other_variant).is_storable = True
        component = self.env["product.product"].create({"name": "Sofa Leg"})
        own, template_wide, foreign, kit = self.env["mrp.bom"].create(
            [
                {
                    "product_tmpl_id": self.product_7_template.id,
                    "product_id": product.id if product else False,
                    "type": bom_type,
                    "product_qty": 1,
                    "bom_line_ids": [
                        Command.create({"product_id": component.id, "product_qty": 1})
                    ],
                }
                for product, bom_type in (
                    (variant, "normal"),
                    (False, "normal"),
                    (other_variant, "normal"),
                    (self.product_7_3, "phantom"),
                )
            ]
        )
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": variant.id,
                "warehouse_id": self.warehouse_1.id,
                "location_id": self.stock_location.id,
                "product_min_qty": 1,
                "product_max_qty": 2,
            }
        )
        info = self.env["stock.replenishment.info"].create(
            {"orderpoint_id": orderpoint.id}
        )
        self.assertEqual(info.bom_ids, own | template_wide)
        self.assertNotIn(foreign, info.bom_ids)
        self.assertNotIn(kit, info.bom_ids)

    def test_replenish_plans_with_the_variant_manufacturing_bom(self):
        variant = self.product_7_1
        variant.is_storable = True
        component = self.env["product.product"].create({"name": "Sofa Frame"})
        route = self.warehouse_1.manufacture_pull_id.route_id
        variant.route_ids = route
        self.env["mrp.bom"].create(
            [
                {
                    "product_tmpl_id": self.product_7_template.id,
                    "product_id": product.id if product else False,
                    "type": bom_type,
                    "sequence": sequence,
                    "produce_delay": delay,
                    "product_qty": 1,
                    "bom_line_ids": [
                        Command.create({"product_id": component.id, "product_qty": 1})
                    ],
                }
                for product, bom_type, sequence, delay in (
                    (False, "phantom", 1, 30),
                    (self.product_7_2, "normal", 2, 20),
                    (variant, "normal", 3, 5),
                )
            ]
        )
        wizard = (
            self.env["product.replenish"]
            .with_context(default_product_tmpl_id=self.product_7_template.id)
            .create(
                {
                    "product_id": variant.id,
                    "product_uom_id": self.uom_unit.id,
                    "quantity": 1,
                    "warehouse_id": self.warehouse_1.id,
                    "route_id": route.id,
                }
            )
        )
        rule_delay = sum(route.rule_ids.mapped("delay"))
        expected = fields.Datetime.add(fields.Datetime.now(), days=rule_delay + 5)
        self.assertAlmostEqual(
            wizard.date_planned, expected, delta=timedelta(minutes=1)
        )

    def _unbuild_statements(self, components):
        parts = self.env["product.product"].create(
            [
                {"name": f"Part {index}", "is_storable": True}
                for index in range(components)
            ]
        )
        product = self.env["product.product"].create(
            {"name": f"Assembly {components}", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": part.id, "product_qty": 1})
                    for part in parts
                ],
            }
        )
        for part in parts:
            self._stock(part, 5)
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo_form.bom_id = bom
        mo_form.product_qty = 5
        mo = mo_form.save()
        mo.action_confirm()
        self._produce(mo)
        unbuild = self.env["mrp.unbuild"].create({"mo_id": mo.id, "product_qty": 5})
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.registry.clear_all_caches()
        gc.collect()
        before = self.env.cr.sql_statement_count
        unbuild.action_unbuild()
        self.env.flush_all()
        statements = self.env.cr.sql_statement_count - before
        for part in parts:
            self.assertEqual(
                self.env["stock.quant"]._get_available_quantity(
                    part, self.stock_location
                ),
                5,
            )
        return statements

    def test_unbuild_statements_per_component_are_bounded(self):
        small = self._unbuild_statements(3)
        large = self._unbuild_statements(12)
        # One quant lookup per component, plus one UPDATE the flush splits off
        # when the lines' done date straddles a second.
        self.assertLessEqual(large - small, (12 - 3) + 1, (small, large))

    def test_quantity_changes_back_and_forth_do_not_drift(self):
        product, component = self.env["product.product"].create(
            [
                {"name": "Third Box", "is_storable": True},
                {"name": "Third Part", "is_storable": True},
            ]
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 3,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )

        def new_order(quantity):
            mo_form = Form(self.env["mrp.production"])
            mo_form.product_id = product
            mo_form.bom_id = bom
            mo_form.product_qty = quantity
            mo = mo_form.save()
            mo.action_confirm()
            return mo

        fresh = {qty: new_order(qty).move_raw_ids.product_uom_qty for qty in (7, 10)}
        mo = new_order(10)
        seen = []
        for quantity in (7, 10, 7, 10):
            self.env["change.production.qty"].create(
                {"mo_id": mo.id, "product_qty": quantity}
            ).change_prod_qty()
            seen.append(mo.move_raw_ids.product_uom_qty)
        self.assertEqual(seen, [fresh[7], fresh[10], fresh[7], fresh[10]])

    def test_quantity_change_keeps_a_hand_edited_component(self):
        product, component = self.env["product.product"].create(
            [
                {"name": "Edited Box", "is_storable": True},
                {"name": "Edited Part", "is_storable": True},
            ]
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = product
        mo_form.bom_id = bom
        mo_form.product_qty = 10
        mo = mo_form.save()
        mo.action_confirm()
        mo.move_raw_ids.product_uom_qty = 15
        self.env["change.production.qty"].create(
            {"mo_id": mo.id, "product_qty": 20}
        ).change_prod_qty()
        self.assertEqual(mo.move_raw_ids.product_uom_qty, 30)

    def test_split_refuses_a_part_that_is_not_positive(self):
        mo, _bom, _p_final, _p1, _p2 = self.generate_mo(qty_final=10)
        for quantities in ((10, 0), (12, -2)):
            wizard = self.env["mrp.production.split"].create(
                {
                    "production_id": mo.id,
                    "production_detailed_vals_ids": [Command.clear()]
                    + [Command.create({"quantity": qty}) for qty in quantities],
                }
            )
            with self.assertRaisesRegex(UserError, "Every part of a split"):
                wizard.action_split()
            self.assertEqual(mo.product_qty, 10)
            self.assertFalse(mo.production_group_id.production_ids - mo)

    def _quantity_change_order(self, components):
        warehouse = self.env.ref("stock.warehouse0")
        product = self.env["product.product"].create(
            {"name": "Rescaled", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": qty})
                    for component, qty in components
                ],
            }
        )
        mo = self.env["mrp.production"].create(
            {
                "product_id": product.id,
                "product_qty": 1.0,
                "picking_type_id": warehouse.manu_type_id.id,
            }
        )
        mo.action_confirm()
        return mo

    def test_quantity_change_reserves_and_procures_every_component(self):
        warehouse = self.env.ref("stock.warehouse0")
        warehouse.manufacture_to_resupply = True
        stocked, made, consumable = self.env["product.product"].create(
            [
                {"name": "Rescaled stocked", "is_storable": True},
                {
                    "name": "Rescaled made to order",
                    "is_storable": True,
                    "route_ids": [
                        Command.set(
                            [
                                warehouse.manufacture_pull_id.route_id.id,
                                warehouse.mto_pull_id.route_id.id,
                            ]
                        )
                    ],
                },
                {"name": "Rescaled consumable"},
            ]
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": made.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": consumable.id, "product_qty": 1})
                ],
            }
        )
        warehouse.mto_pull_id.route_id.active = True
        self.env["stock.quant"]._update_available_quantity(
            stocked, warehouse.lot_stock_id, 5
        )
        mo = self._quantity_change_order([(stocked, 2), (made, 1), (consumable, 1)])
        children = mo._get_children()
        self.assertEqual(sum(children.mapped("product_qty")), 1)

        self.env["change.production.qty"].create(
            {"mo_id": mo.id, "product_qty": 3}
        ).change_prod_qty()

        moves = {move.product_id: move for move in mo.move_raw_ids}
        self.assertEqual(
            [
                (moves[p].product_uom_qty, moves[p].quantity, moves[p].state)
                for p in (stocked, made, consumable)
            ],
            [
                (6.0, 5.0, "partially_available"),
                (3.0, 0.0, "waiting"),
                (3.0, 3.0, "assigned"),
            ],
        )
        self.assertEqual(mo.reservation_state, "confirmed")
        children = mo._get_children()
        self.assertEqual(children.product_id, made)
        self.assertEqual(sum(children.mapped("product_qty")), 3)

    def test_quantity_change_statements_per_component_are_bounded(self):
        warehouse = self.env.ref("stock.warehouse0")
        counts = []
        for size in (3, 12):
            components = self.env["product.product"].create(
                [
                    {"name": "Rescaled %s/%s" % (index, size), "is_storable": True}
                    for index in range(size)
                ]
            )
            for component in components:
                self.env["stock.quant"]._update_available_quantity(
                    component, warehouse.lot_stock_id, 4
                )
            mo = self._quantity_change_order([(c, 2) for c in components])
            wizard = self.env["change.production.qty"].create(
                {"mo_id": mo.id, "product_qty": 3}
            )
            self.env.flush_all()
            self.env.invalidate_all()
            self.env.registry.clear_all_caches()
            gc.collect()
            before = self.env.cr.sql_statement_count
            wizard.change_prod_qty()
            self.env.flush_all()
            counts.append(self.env.cr.sql_statement_count - before)
            self.assertEqual(set(mo.move_raw_ids.mapped("quantity")), {4.0})
        self.assertLess((counts[1] - counts[0]) / 9, 2, counts)
