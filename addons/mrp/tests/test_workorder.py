import gc
from datetime import datetime, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWorkorderAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["mrp.workcenter"].search([]).write({"working_state": "normal"})
        cls.wc = cls.env["mrp.workcenter"].create(
            {"name": "AUD WC", "time_efficiency": 100, "costs_hour": 10}
        )
        cls.wc2 = cls.env["mrp.workcenter"].create(
            {"name": "AUD WC2", "time_efficiency": 100, "costs_hour": 10}
        )

    def _mo(self, n_ops=1, qty=5, tag="T"):
        fin = self.env["product.product"].create(
            {"name": f"{tag} fin", "is_storable": True}
        )
        comp = self.env["product.product"].create(
            {"name": f"{tag} comp", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": fin.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": comp.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": f"Op{i}",
                            "workcenter_id": self.wc.id,
                            "time_cycle_manual": 10,
                            "sequence": (i + 1) * 5,
                        }
                    )
                    for i in range(n_ops)
                ],
            }
        )
        mo = self.env["mrp.production"].create(
            {"product_id": fin.id, "bom_id": bom.id, "product_qty": qty}
        )
        mo.action_confirm()
        self.env.flush_all()
        return mo

    def test_replanning_an_unconflicted_workorder_keeps_its_slot(self):
        mo = self._mo(tag="R")
        # A slot starting now is in the past a second later, and replanning
        # anchors on the clock: plan in the future to measure conflicts only.
        mo.date_start = fields.Datetime.now() + timedelta(days=7)
        mo.button_plan()
        self.env.flush_all()
        wo = mo.workorder_ids
        planned = (wo.date_start, wo.date_end)
        wo.action_replan()
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(
            (wo.date_start, wo.date_end),
            planned,
            "replanning a work order that conflicts with nothing moved it",
        )

    def _open_timers(self, workorders):
        return self.env["mrp.workcenter.productivity"].create(
            [
                wo._prepare_timeline_vals(wo.duration, fields.Datetime.now())
                for wo in workorders
            ]
        )

    def test_button_start_opens_a_timer_when_the_layer_wants_one(self):
        mo = self._mo(tag="B")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        self.assertEqual(
            bool(wo.time_ids.filtered(lambda time: not time.date_end)),
            wo._is_timer_start_required(),
            "button_start and _is_timer_start_required disagreed on whether this "
            "work order is being timed for the acting user",
        )

    def test_pausing_many_workorders_closes_every_timer(self):
        mo = self._mo(n_ops=3, tag="P")
        self._open_timers(mo.workorder_ids)
        self.env.flush_all()
        productivity = self.env["mrp.workcenter.productivity"]
        domain = [
            ("workorder_id", "in", mo.workorder_ids.ids),
            ("date_end", "=", False),
        ]
        self.assertEqual(productivity.search_count(domain), 3)
        mo.workorder_ids.button_pending()
        self.env.flush_all()
        self.assertEqual(
            productivity.search_count(domain),
            0,
            "button_pending on a recordset closed only some of the timers",
        )

    def test_is_user_working_is_per_user(self):
        mo = self._mo(tag="U")
        wo = mo.workorder_ids
        self._open_timers(wo)
        self.env.flush_all()
        other = self.env["res.users"].create(
            {
                "name": "Audit Other",
                "login": "audit_other_user",
                "group_ids": [
                    Command.link(self.env.ref("base.group_user").id),
                    Command.link(self.env.ref("mrp.group_mrp_user").id),
                ],
            }
        )
        self.assertTrue(wo.is_user_working)
        self.assertFalse(
            wo.with_user(other).is_user_working,
            "is_user_working leaked another user's timer (no depends_context('uid'))",
        )

    def test_is_user_working_refreshes_when_a_timer_opens(self):
        mo = self._mo(tag="W")
        wo = mo.workorder_ids
        self.assertFalse(wo.is_user_working)
        self._open_timers(wo)
        self.env.flush_all()
        self.assertTrue(
            wo.is_user_working,
            "is_user_working is stale after a timer opened (no @api.depends)",
        )

    def test_scrap_count_refreshes(self):
        mo = self._mo(tag="S")
        wo = mo.workorder_ids
        self.assertEqual(wo.scrap_count, 0)
        component = mo.move_raw_ids[0].product_id
        self.env["stock.scrap"].create(
            {
                "product_id": component.id,
                "product_uom_id": component.uom_id.id,
                "scrap_qty": 1,
                "workorder_id": wo.id,
                "production_id": mo.id,
                "company_id": mo.company_id.id,
            }
        )
        self.env.flush_all()
        self.assertEqual(
            wo.scrap_count, 1, "scrap_count is stale (no @api.depends('scrap_ids'))"
        )

    def test_qty_ready_is_zero_once_cancelled(self):
        mo = self._mo(tag="Q")
        wo = mo.workorder_ids
        self.assertGreater(wo.qty_ready, 0)
        wo.action_cancel()
        self.env.flush_all()
        self.assertEqual(
            wo.qty_ready, 0, "qty_ready is stale after a state change (missing depends)"
        )

    def test_duration_unit_for_a_fractional_quantity(self):
        mo = self._mo(tag="D")
        wo = mo.workorder_ids
        wo.write({"duration": 60.0})
        self.env.flush_all()
        wo.write({"qty_produced": 0.5})
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_unit,
            120.0,
            places=2,
            msg="duration_unit divides by max(qty_produced, 1)",
        )

    def test_duration_expected_scales_on_a_started_workorder(self):
        mo = self._mo(tag="C")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        before = wo.duration_expected
        self.env["change.production.qty"].create(
            {"mo_id": mo.id, "product_qty": 20}
        ).change_prod_qty()
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_expected,
            before * 4,
            places=2,
            msg="quadrupling the quantity left a started work order's duration frozen",
        )

    def test_time_efficiency_applies_without_an_operation(self):
        mo = self._mo(tag="E")
        wo = mo.workorder_ids
        wo.operation_id = False
        wo.workcenter_id = self.wc
        wo.duration_expected = 100
        self.env.flush_all()
        self.wc2.resource_id.time_efficiency = 200
        wo.write({"workcenter_id": self.wc2.id})
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertAlmostEqual(
            wo.duration_expected,
            50.0,
            places=2,
            msg="a twice-as-fast work center did not change the expected duration",
        )

    def test_an_operation_added_later_keeps_the_routing_order(self):
        mo = self._mo(n_ops=3, tag="O")
        self.env["mrp.routing.workcenter"].create(
            {
                "name": "Prep",
                "bom_id": mo.bom_id.id,
                "sequence": 1,
                "workcenter_id": self.wc.id,
                "time_cycle_manual": 5,
            }
        )
        self.env.flush_all()
        mo.action_update_bom()
        self.env.flush_all()
        mo.invalidate_recordset()
        self.assertEqual(
            mo.workorder_ids.mapped("name")[0],
            "Prep",
            "an operation whose routing sequence is 1 did not sort first",
        )

    def test_a_derived_state_cannot_be_set_by_hand(self):
        mo = self._mo(tag="B")
        wo = mo.workorder_ids
        with self.assertRaises(UserError):
            wo.set_state("blocked")
        wo.action_cancel()
        self.env.flush_all()
        self.assertEqual(wo.state, "cancel")
        wo.set_state("ready")
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.state, "ready")

    def test_writing_both_dates_moves_the_workorder(self):
        mo = self._mo(tag="X")
        wo = mo.workorder_ids
        wo.write({"date_start": datetime(2026, 9, 1, 8, 0), "duration_expected": 60})
        self.env.flush_all()
        wo.invalidate_recordset()
        duration = wo.duration_expected

        wo.write(
            {
                "date_start": datetime(2026, 9, 2, 9, 0),
                "date_end": datetime(2026, 9, 2, 18, 0),
            }
        )
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.date_start, datetime(2026, 9, 2, 9, 0))
        self.assertEqual(wo.duration_expected, duration, "a move must keep the length")
        self.assertNotEqual(wo.date_end, datetime(2026, 9, 2, 18, 0))

        wo.write(
            {
                "date_start": datetime(2026, 9, 3, 8, 0),
                "date_end": datetime(2026, 9, 3, 17, 0),
                "duration_expected": 540,
            }
        )
        self.env.flush_all()
        wo.invalidate_recordset()
        self.assertEqual(wo.date_end, datetime(2026, 9, 3, 17, 0))
        self.assertEqual(wo.duration_expected, 540)

    def test_starting_a_workorder_does_not_book_a_whole_day(self):
        mo = self._mo(tag="Y")
        wo = mo.workorder_ids
        wo.button_start()
        self.env.flush_all()
        wo.invalidate_recordset()
        span = (wo.date_end - wo.date_start).total_seconds() / 60
        self.assertLess(
            span,
            wo.duration_expected * 3,
            "starting a 50-minute job booked the work center for %.1f minutes" % span,
        )

    def test_a_double_booked_workorder_is_never_silent(self):
        mo_a = self._mo(tag="CA")
        mo_a.button_plan()
        self.env.flush_all()
        a = mo_a.workorder_ids
        a.button_start()
        self.env.flush_all()
        mo_b = self._mo(tag="CB")
        b = mo_b.workorder_ids
        b.workcenter_id = a.workcenter_id
        b.with_context(bypass_duration_calculation=True).write(
            {"date_start": a.date_start, "date_end": a.date_end}
        )
        self.env.flush_all()
        self.env.invalidate_all()
        planner_start, _stop = a.workcenter_id._get_first_available_slot(
            a.date_start, b.duration_expected
        )
        self.assertGreater(
            planner_start, a.date_start, "the planner should refuse the taken slot"
        )
        self.assertTrue(
            b.show_json_popover,
            "the planner refuses the slot but the popover reports nothing",
        )
        self.assertIn("already booked", b.json_popover)

    def _configurable_bom(self):
        template = self.env["product.template"].create(
            {"name": "WO configurable", "is_storable": True}
        )
        attributes = self.env["product.attribute"].create(
            [
                {
                    "name": "WO size",
                    "create_variant": "always",
                    "value_ids": [
                        Command.create({"name": "WO small"}),
                        Command.create({"name": "WO large"}),
                    ],
                },
                {
                    "name": "WO finish",
                    "create_variant": "no_variant",
                    "value_ids": [
                        Command.create({"name": "WO matte"}),
                        Command.create({"name": "WO gloss"}),
                    ],
                },
            ]
        )
        size_values, finish_values = (
            self.env["product.template.attribute.line"]
            .create(
                [
                    {
                        "product_tmpl_id": template.id,
                        "attribute_id": attribute.id,
                        "value_ids": [Command.set(attribute.value_ids.ids)],
                    }
                    for attribute in attributes
                ]
            )
            .mapped("product_template_value_ids")
            .grouped("attribute_id")
            .values()
        )
        component, kit, finish_kit, kit_part = self.env["product.product"].create(
            [
                {"name": "WO part", "is_storable": True},
                {"name": "WO kit"},
                {"name": "WO finish kit"},
                {"name": "WO kit part", "is_storable": True},
            ]
        )
        for product, operation in ((kit, "Kit op"), (finish_kit, "Finish op")):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "type": "phantom",
                    "bom_line_ids": [
                        Command.create({"product_id": kit_part.id, "product_qty": 1})
                    ],
                    "operation_ids": [
                        Command.create(
                            {
                                "name": operation,
                                "workcenter_id": self.wc2.id,
                                "time_cycle_manual": 7,
                            }
                        )
                    ],
                }
            )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_qty": 1,
                "allow_operation_dependencies": True,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 2}),
                    Command.create({"product_id": kit.id, "product_qty": 1}),
                    Command.create(
                        {
                            "product_id": finish_kit.id,
                            "product_qty": 1,
                            "bom_product_template_attribute_value_ids": [
                                Command.set(finish_values[0].ids)
                            ],
                        }
                    ),
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": name,
                            "workcenter_id": workcenter.id,
                            "time_cycle_manual": minutes,
                            "sequence": sequence,
                            "bom_product_template_attribute_value_ids": [
                                Command.set(values.ids)
                            ],
                        }
                    )
                    for name, workcenter, minutes, sequence, values in (
                        ("Cut", self.wc, 10, 5, size_values[:0]),
                        ("Paint", self.wc2, 20, 10, size_values[0]),
                        ("Pack", self.wc, 5, 15, size_values[:0]),
                    )
                ],
            }
        )
        cut, _paint, pack = bom.operation_ids.sorted("sequence")
        pack.blocked_by_operation_ids = cut
        return template, bom, finish_values

    def _workorder_fingerprint(self, productions):
        return [
            (
                production.product_id.display_name,
                production.product_qty,
                production.never_product_template_attribute_value_ids.ids,
                production.state,
                production.date_end,
                sorted(
                    (
                        workorder.name,
                        workorder.workcenter_id.name,
                        workorder.sequence,
                        workorder.duration_expected,
                        workorder.state,
                        tuple(
                            sorted(workorder.blocked_by_workorder_ids.mapped("name"))
                        ),
                        tuple(sorted(workorder.move_raw_ids.product_id.mapped("name"))),
                    )
                    for workorder in production.workorder_ids
                ),
            )
            for production in productions
        ]

    def test_orders_created_together_get_the_work_orders_of_orders_created_alone(self):
        template, bom, finish_values = self._configurable_bom()
        date_start = fields.Datetime.now().replace(microsecond=0) + timedelta(days=5)
        vals_list = [
            {
                "product_id": variant.id,
                "bom_id": bom.id,
                "product_qty": quantity,
                "date_start": date_start,
                "never_product_template_attribute_value_ids": [Command.set(finish.ids)],
            }
            for variant in template.product_variant_ids
            for finish in finish_values
            for quantity in (1, 3)
        ]
        Production = self.env["mrp.production"]
        together = Production.create([dict(vals) for vals in vals_list])
        alone = Production.union(*(Production.create(dict(vals)) for vals in vals_list))
        self.assertEqual(
            {
                name
                for production in together
                for name in production.workorder_ids.mapped("name")
            },
            {"Cut", "Paint", "Pack", "Kit op", "Finish op"},
        )
        self.assertEqual(
            self._workorder_fingerprint(together), self._workorder_fingerprint(alone)
        )
        (together | alone).action_confirm()
        self.assertEqual(
            self._workorder_fingerprint(together), self._workorder_fingerprint(alone)
        )

    def test_a_quantity_change_keeps_the_work_orders_of_a_no_variant_kit(self):
        template, bom, finish_values = self._configurable_bom()
        production = self.env["mrp.production"].create(
            {
                "product_id": template.product_variant_ids[0].id,
                "bom_id": bom.id,
                "never_product_template_attribute_value_ids": [
                    Command.set(finish_values[0].ids)
                ],
            }
        )
        workorders = production.workorder_ids
        self.assertIn("Finish op", workorders.mapped("name"))
        production.write({"product_qty": 2})
        self.assertEqual(production.workorder_ids, workorders)
        self.assertEqual(production.workorder_ids.exists(), workorders)

    def test_creating_orders_with_operations_costs_a_bounded_query_count_per_order(
        self,
    ):
        components = self.env["product.product"].create(
            [
                {"name": "WO slope comp %s" % index, "is_storable": True}
                for index in range(3)
            ]
        )
        product = self.env["product.product"].create(
            {"name": "WO slope", "is_storable": True}
        )
        self.assertTrue(self.wc.resource_calendar_id)
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 2})
                    for component in components
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Slope op",
                            "workcenter_id": self.wc.id,
                            "time_cycle_manual": 10,
                        }
                    )
                ],
            }
        )
        date_start = fields.Datetime.now().replace(microsecond=0) + timedelta(days=5)

        def cost(count):
            self.env.flush_all()
            self.env.invalidate_all()
            self.env.registry.clear_all_caches()
            gc.collect()
            before = self.env.cr.sql_statement_count
            self.env["mrp.production"].create(
                [
                    {
                        "product_id": product.id,
                        "bom_id": bom.id,
                        "product_qty": 1 + index,
                        "date_start": date_start,
                    }
                    for index in range(count)
                ]
            )
            self.env.flush_all()
            return self.env.cr.sql_statement_count - before

        few, many = cost(3), cost(12)
        self.assertLess((many - few) / 9, 1, (few, many))

    def test_orders_created_together_end_when_orders_created_alone_do(self):
        _template, bom, finish_values = self._configurable_bom()
        occupying = self._mo(n_ops=2, qty=30, tag="Occupying")
        occupying.date_start = fields.Datetime.now().replace(microsecond=0) + timedelta(
            days=2
        )
        occupying.button_plan()
        self.assertTrue(occupying.workorder_ids.reservation_id)
        start = occupying.date_start - timedelta(hours=3)
        vals_list = [
            {
                "product_id": _template.product_variant_ids[index % 2].id,
                "bom_id": bom.id,
                "product_qty": 1 + index,
                "date_start": start + timedelta(hours=7 * index),
                "never_product_template_attribute_value_ids": [
                    Command.set(finish_values[index % 2].ids)
                ],
            }
            for index in range(8)
        ]
        Production = self.env["mrp.production"]
        together = Production.create([dict(vals) for vals in vals_list])
        alone = Production.union(*(Production.create(dict(vals)) for vals in vals_list))
        self.assertEqual(together.mapped("date_end"), alone.mapped("date_end"))
        self.assertEqual(
            len(set(together.mapped("date_end"))), 8, together.mapped("date_end")
        )
