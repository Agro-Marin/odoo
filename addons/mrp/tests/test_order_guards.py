import gc
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestOrderGuards(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.finished, cls.component, cls.byproduct = cls.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Component", "is_storable": True},
                {"name": "Byproduct", "is_storable": True},
            ]
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 2})
                ],
            }
        )

    def _production(self, qty, bom=None):
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = bom or self.bom
        form.product_qty = qty
        return form.save()

    def _produced(self, qty):
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(qty)
        production.action_confirm()
        production.qty_producing = qty
        production.move_raw_ids.picked = True
        production.button_mark_done()
        return production

    def test_a_done_unbuild_is_not_run_again(self):
        production = self._produced(2)
        unbuild = self.env["mrp.unbuild"].create(
            {"mo_id": production.id, "product_qty": 1}
        )
        unbuild.action_unbuild()
        with self.assertRaises(UserError):
            unbuild.action_unbuild()

    def test_an_unbuild_takes_the_manufacturing_bom_not_the_kit(self):
        self.bom.sequence = 2
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "type": "phantom",
                "sequence": 1,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 1})
                ],
            }
        )
        unbuild = self.env["mrp.unbuild"].create(
            {"product_id": self.finished.id, "product_qty": 1}
        )
        self.assertEqual(unbuild.bom_id, self.bom)

    def test_a_second_unbuild_returns_the_serial_the_first_left(self):
        self.component.tracking = "serial"
        self.bom.bom_line_ids.product_qty = 1
        serials = self.env["stock.lot"].create(
            [{"name": name, "product_id": self.component.id} for name in ("S1", "S2")]
        )
        for serial in serials:
            self.env["stock.quant"]._update_available_quantity(
                self.component, self.stock_location, 1, lot_id=serial
            )
        production = self._production(2)
        production.action_confirm()
        production.action_assign()
        production.qty_producing = 2
        production.move_raw_ids.picked = True
        production.button_mark_done()
        unbuilds = self.env["mrp.unbuild"]
        for _index in range(2):
            unbuild = self.env["mrp.unbuild"].create(
                {"mo_id": production.id, "product_qty": 1}
            )
            unbuild.action_unbuild()
            unbuilds |= unbuild
        self.assertEqual(
            sorted(unbuilds.produce_line_ids.move_line_ids.lot_id.mapped("name")),
            ["S1", "S2"],
        )

    def test_a_closed_order_keeps_its_quantity(self):
        production = self._produced(2)
        wizard = self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 4}
        )
        with self.assertRaises(UserError):
            wizard.change_prod_qty()
        self.assertEqual(production.product_qty, 2)

    def test_a_quantity_change_keeps_a_partial_record(self):
        production = self._production(10)
        production.action_confirm()
        production.qty_producing = 4
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 12}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 4)

    def test_a_lowered_quantity_caps_the_partial_record(self):
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(10)
        production.action_confirm()
        production.action_assign()
        with Form(production) as form:
            form.qty_producing = 4
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 3}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 3)
        production.button_mark_done()
        self.assertEqual(production.qty_produced, 3)

    def test_a_quantity_change_follows_an_order_producing_all(self):
        production = self._production(10)
        production.action_confirm()
        production.qty_producing = 10
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 12}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 12)

    def test_serial_numbers_are_trimmed_and_deduplicated(self):
        self.finished.tracking = "serial"
        production = self._production(2)
        production.action_confirm()
        wizard = self.env["mrp.production.serials"].create(
            {"production_id": production.id, "serial_numbers": "SN1\r\nSN2 \n SN1\n"}
        )
        self.assertEqual(wizard._get_names_from_serial_numbers(), ["SN1", "SN2"])

    def test_a_procured_order_sends_only_its_product_downstream(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        delivery = self.env["stock.move"].create(
            {
                "product_id": self.finished.id,
                "product_uom_qty": 1,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "procure_method": "make_to_order",
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": self.bom.id,
                "product_qty": 1,
                "move_dest_ids": [Command.link(delivery.id)],
            }
        )
        main = production.move_finished_ids - production.move_byproduct_ids
        self.assertEqual(main.move_dest_ids, delivery)
        self.assertFalse(production.move_byproduct_ids.move_dest_ids)

    def test_orders_created_together_keep_their_own_byproducts(self):
        other, other_byproduct = self.env["product.product"].create(
            [
                {"name": "Other finished", "is_storable": True},
                {"name": "Other byproduct", "is_storable": True},
            ]
        )
        locations = {
            "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id,
        }
        productions = self.env["mrp.production"].create(
            [
                {
                    "product_id": product.id,
                    "product_qty": 1,
                    "move_byproduct_ids": [
                        Command.create(
                            {
                                "product_id": byproduct.id,
                                "product_uom_qty": 1,
                                **locations,
                            }
                        )
                    ],
                }
                for product, byproduct in (
                    (self.finished, self.byproduct),
                    (other, other_byproduct),
                )
            ]
        )
        for production, byproduct in zip(
            productions, (self.byproduct, other_byproduct), strict=True
        ):
            self.assertEqual(
                production.move_finished_ids.product_id,
                production.product_id | byproduct,
            )

    def test_unreserving_keeps_the_byproduct_to_produce(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 10
        )
        production = self._production(2)
        production.action_confirm()
        production.qty_producing = 2
        production.action_unreserve()
        production.action_assign()
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.assertEqual(production.move_byproduct_ids.state, "done")
        self.assertEqual(production.move_byproduct_ids.quantity, 2)

    def test_a_bom_unit_change_outdates_its_orders(self):
        production = self._production(1)
        self.assertFalse(production.is_outdated_bom)
        self.bom.product_uom_id = self.uom_dozen
        self.assertTrue(production.is_outdated_bom)

    def test_a_bom_type_change_outdates_its_orders(self):
        production = self._production(1)
        self.assertFalse(production.is_outdated_bom)
        self.bom.type = "phantom"
        self.assertTrue(production.is_outdated_bom)

    def test_an_archived_bom_is_not_counted(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        self.bom.action_archive()
        self.env.invalidate_all()
        self.assertEqual(self.component.used_in_bom_count, 0)
        self.assertEqual(self.byproduct.bom_count, 0)
        self.assertEqual(self.byproduct.product_tmpl_id.bom_count, 0)

    def test_lead_days_given_no_bom_look_the_bom_up(self):
        self.bom.produce_delay = 5
        rule = self.warehouse_1.manufacture_pull_id
        delays, _descriptions = rule._get_lead_days(
            self.finished, bom=self.env["mrp.bom"]
        )
        self.assertEqual(delays["no_bom_found_delay"], 0)
        self.assertEqual(delays["manufacture_delay"], 5)

    def test_the_settings_form_leaves_orders_alone_until_saved(self):
        production = self._production(1)
        production.action_confirm()
        production.is_locked = False
        form = Form(self.env["res.config.settings"])
        self.assertFalse(production.is_locked, "opening the form re-locked it")
        form.group_unlocked_by_default = True
        form.group_unlocked_by_default = False
        self.assertFalse(production.is_locked, "an unsaved toggle wrote it")
        form.group_mrp_byproducts = not form.group_mrp_byproducts
        form.save().execute()
        self.assertFalse(production.is_locked, "an unrelated save re-locked it")

    def test_unlocking_by_default_applies_on_save(self):
        production = self._production(1)
        production.action_confirm()
        self.assertTrue(production.is_locked)
        self.env["res.config.settings"].create(
            {"group_unlocked_by_default": True}
        ).execute()
        self.assertFalse(production.is_locked)
        self.env["res.config.settings"].create(
            {"group_unlocked_by_default": False}
        ).execute()
        self.assertTrue(production.is_locked)

    def _partially_produced(self, qty, producing):
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(qty)
        production.action_confirm()
        production.action_assign()
        production.qty_producing = producing
        production.set_qty_producing()
        return production

    def _mark_done_counting_posts(self, production, **context):
        Production = self.registry["mrp.production"]
        post_inventory = Production._post_inventory
        posted = []

        def counting_post(records, cancel_backorder=False):
            if records:
                posted.append(records.ids)
            return post_inventory(records, cancel_backorder=cancel_backorder)

        with patch.object(Production, "_post_inventory", counting_post):
            action = production.with_context(**context).button_mark_done()
        return action, posted

    def test_an_always_backorder_is_posted_once(self):
        production = self._partially_produced(4, 1)
        production.picking_type_id.create_backorder = "always"
        action, posted = self._mark_done_counting_posts(
            production, skip_redirection=True
        )
        self.assertIs(action, True)
        self.assertEqual(posted, [production.ids])
        self.assertEqual(production.state, "done")
        self.assertEqual(len(production.production_group_id.production_ids), 2)

    def test_a_swallowed_always_backorder_still_returns_its_reports(self):
        production = self._partially_produced(4, 1)
        production.picking_type_id.write(
            {"create_backorder": "always", "auto_print_done_production_order": True}
        )
        Production = self.registry["mrp.production"]
        with patch.object(
            Production, "_is_result_return_required", lambda productions: False
        ):
            action, posted = self._mark_done_counting_posts(production)
        self.assertEqual(posted, [production.ids])
        self.assertEqual(action["tag"], "do_multi_print")
        self.assertEqual(
            [report["report_name"] for report in action["params"]["reports"]],
            [self.env.ref("mrp.action_report_production_order").report_name],
        )

    def test_a_draft_order_is_not_marked_done(self):
        production = self._production(2)
        with self.assertRaises(UserError):
            production.button_mark_done()
        self.assertEqual(production.state, "draft")

    def test_a_cancelled_order_is_not_marked_done(self):
        production = self._production(2)
        production.action_confirm()
        production.action_cancel()
        with self.assertRaises(UserError):
            production.button_mark_done()
        self.assertEqual(production.state, "cancel")

    def test_a_fractional_run_costs_its_expected_time_per_unit(self):
        self.bom.operation_ids = [
            Command.create(
                {
                    "name": "Only",
                    "workcenter_id": self.workcenter_2.id,
                    "time_cycle_manual": 30,
                }
            )
        ]
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(0.5)
        production.action_confirm()
        production.qty_producing = 0.5
        production.button_mark_done()
        workorder = production.workorder_ids
        self.assertEqual(workorder.qty_produced, 0.5)
        self.assertTrue(workorder.duration)
        self.assertEqual(workorder.duration_unit, round(workorder.duration / 0.5, 2))

    def test_merged_orders_log_where_they_went(self):
        first, second = self._production(1), self._production(2)
        (first | second).action_confirm()
        action = (first | second).action_merge()
        merged = self.env["mrp.production"].browse(action["res_id"])
        note = "This production has been merge in %s" % merged.display_name
        for production in first | second:
            self.assertTrue(
                any(note in body for body in production.message_ids.mapped("body"))
            )


@tagged("post_install", "-at_install")
class TestProductionStatementGuards(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = (
            cls.env["stock.warehouse"]
            .search([("company_id", "=", cls.env.company.id)], limit=1)
            .lot_stock_id
        )
        cls.workcenter = cls.env["mrp.workcenter"].create({"name": "Guarded"})

    def _bom(self, operations=0):
        # Every measurement gets its own products and stock, so what an earlier
        # size left reserved does not change what a later one costs.
        finished, *components = self.env["product.product"].create(
            [{"name": "Guarded %s" % index, "is_storable": True} for index in range(3)]
        )
        for component in components:
            self.env["stock.quant"]._update_available_quantity(
                component, self.stock_location, 1000
            )
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                    for component in components
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Operation %s" % index,
                            "workcenter_id": self.workcenter.id,
                            "time_cycle_manual": 10,
                        }
                    )
                    for index in range(operations)
                ],
            }
        )

    def _orders(self, count, qty=2, operations=0):
        bom = self._bom(operations)
        return self.env["mrp.production"].create(
            [
                {
                    "product_id": bom.product_tmpl_id.product_variant_id.id,
                    "bom_id": bom.id,
                    "product_qty": qty,
                }
                for _index in range(count)
            ]
        )

    def _reserved(self, count, qty=2):
        productions = self._orders(count, qty)
        productions.action_confirm()
        productions.action_assign()
        return productions

    def statements(self, productions, action):
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.registry.clear_all_caches()
        gc.collect()
        productions = productions.browse(productions.ids)
        before = self.env.cr.sql_statement_count
        action(productions)
        self.env.flush_all()
        return self.env.cr.sql_statement_count - before

    def test_mark_done_preflight_statements_do_not_grow_with_orders(self):
        def preflight(count):
            return self.statements(
                self._reserved(count),
                lambda productions: productions.pre_button_mark_done(),
            )

        preflight(1)
        self.assertEqual(preflight(2), preflight(6))

    def test_confirming_one_operation_orders_does_not_grow_with_orders(self):
        def confirm(count):
            return self.statements(
                self._orders(count, operations=1),
                lambda productions: productions.action_confirm(),
            )

        confirm(1)
        self.assertEqual(confirm(2), confirm(6))

    def test_planning_by_availability_does_not_grow_with_orders(self):
        def plan(count):
            return self.statements(
                self._orders(count),
                lambda productions: (
                    productions.action_plan_with_components_availability()
                ),
            )

        plan(1)
        self.assertEqual(plan(2), plan(6))

    def test_backorder_split_grows_by_its_line_writes_only(self):
        def split(count):
            productions = self._reserved(count, qty=4)
            for production in productions:
                production.qty_producing = 1
                production.set_qty_producing()
            return self.statements(
                productions,
                lambda productions: productions.with_context(
                    skip_backorder=True, mo_ids_to_backorder=productions.ids
                ).button_mark_done(),
            )

        split(1)
        # Three statements per order remain: the consume-line insert (an
        # x2many written per record) and the reservation line moved onto the
        # backorder, whose write flushes and re-sums the move quantity. The
        # slack of one per order absorbs an ormcache miss that depends on what
        # ran before; the per-order split this guards against cost thirteen.
        self.assertLessEqual(split(6) - split(2), 4 * 4)
