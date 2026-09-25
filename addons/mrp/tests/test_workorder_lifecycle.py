from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import Command, fields
from odoo.tests import Form, tagged

from .common import TestMrpCommon
from odoo.addons.mrp.models.mrp_workorder import MrpWorkorder


@tagged("post_install", "-at_install")
class TestWorkorderLifecycle(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.finished, cls.component = cls.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Component", "is_storable": True},
            ]
        )
        cls.bom = cls._routed_bom(
            cls.finished, cls.component, "first", "second", workcenter=cls.workcenter_2
        )
        cls.first, cls.second = cls.bom.operation_ids.sorted("sequence")

    def test_overlapping_reasons_of_one_category_count_once(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        zone = ZoneInfo(workorder.workcenter_id.resource_id.tz or "UTC")
        monday = (
            datetime(2026, 9, 21, 9, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
        )
        self._timers(
            workorder,
            ("mrp.block_reason0", monday, monday + timedelta(minutes=60)),
            (
                "mrp.block_reason1",
                monday + timedelta(minutes=30),
                monday + timedelta(minutes=90),
            ),
        )
        merged = workorder.workcenter_id._get_working_minutes_batch(
            [(monday, monday + timedelta(minutes=90))]
        )[0]
        self.assertGreater(merged, 0)
        self.env.flush_all()
        workorder.invalidate_recordset()
        self.assertEqual(workorder.duration, merged)

    def test_the_deviation_follows_a_written_duration(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        self.assertEqual(workorder.duration_expected, 60)
        workorder.duration = 30
        self.env.flush_all()
        workorder.invalidate_recordset()
        self.assertEqual(workorder.duration, 30)
        self.assertEqual(workorder.duration_percent, 50)

    def test_lowering_the_duration_keeps_a_running_timer(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        start = fields.Datetime.now() - timedelta(hours=3)
        closed, running = self._timers(
            workorder,
            ("mrp.block_reason7", start, start + timedelta(minutes=60)),
            ("mrp.block_reason7", start + timedelta(minutes=90), False),
        )
        workorder.duration = 50
        self.assertTrue(running.exists())
        self.assertTrue(closed.exists())

    def test_setting_to_do_keeps_a_blocked_order_blocked(self):
        production = self._confirmed_production(self.bom)
        production.button_plan()
        _first, second = production.workorder_ids.sorted(
            lambda workorder: workorder.operation_id.sequence
        )
        self.assertEqual(second.state, "blocked")
        second.set_state("ready")
        self.assertEqual(second.state, "blocked")

    def _planned_pair(self):
        production = self._confirmed_production(self.bom)
        production.button_plan()
        first, second = production.workorder_ids.sorted(
            lambda workorder: workorder.operation_id.sequence
        )
        self.assertEqual(second.blocked_by_workorder_ids, first)
        return production, first, second

    def test_update_bom_follows_the_current_dependencies(self):
        self.bom.allow_operation_dependencies = True
        self.first.blocked_by_operation_ids = self.second
        production = self._confirmed_production(self.bom)
        production.button_plan()
        production.button_unplan()
        self.bom.allow_operation_dependencies = False
        self.assertTrue(production.is_outdated_bom)
        production.action_update_bom()
        production.button_plan()
        first, second = production.workorder_ids.sorted(
            lambda workorder: workorder.operation_id.sequence
        )
        self.assertFalse(first.blocked_by_workorder_ids)
        self.assertEqual(second.blocked_by_workorder_ids, first)

    def test_a_drawn_dependency_survives_replanning(self):
        production, _first, second = self._planned_pair()
        second.blocked_by_workorder_ids = [Command.clear()]
        production.workorder_ids.action_replan()
        production.button_unplan()
        production.button_plan()
        self.assertFalse(second.blocked_by_workorder_ids)

    def test_an_added_work_order_keeps_the_drawn_dependencies(self):
        production, first, second = self._planned_pair()
        second.blocked_by_workorder_ids = [Command.clear()]
        third_operation = self.env["mrp.routing.workcenter"].create(
            {
                "name": "third",
                "bom_id": self.bom.id,
                "workcenter_id": self.workcenter_2.id,
                "sequence": 5,
            }
        )
        third = self.env["mrp.workorder"].create(
            {
                "name": "third",
                "production_id": production.id,
                "operation_id": third_operation.id,
                "workcenter_id": self.workcenter_2.id,
                "product_uom_id": production.product_uom_id.id,
            }
        )
        self.assertFalse(second.blocked_by_workorder_ids)
        self.assertEqual(third.blocked_by_workorder_ids, second)
        self.assertFalse(first.blocked_by_workorder_ids)

    def test_update_bom_rebuilds_a_drawn_dependency(self):
        production, first, second = self._planned_pair()
        second.blocked_by_workorder_ids = [Command.clear()]
        production.action_update_bom()
        self.assertEqual(second.blocked_by_workorder_ids, first)

    def test_moving_an_operation_leaves_its_predecessors_behind(self):
        self.bom.allow_operation_dependencies = True
        self.second.blocked_by_operation_ids = self.first
        other_bom = self.bom.copy()
        self.second.bom_id = other_bom
        self.assertFalse(self.second.blocked_by_operation_ids)
        self.assertEqual(self.first.bom_id, self.bom)

    def test_rewriting_the_bom_keeps_the_dependencies(self):
        self.bom.allow_operation_dependencies = True
        self.second.blocked_by_operation_ids = self.first
        self.second.bom_id = self.bom
        self.assertEqual(self.second.blocked_by_operation_ids, self.first)

    def test_recategorizing_a_reason_leaves_its_siblings(self):
        reason, sibling = self.env.ref("mrp.block_reason0") | self.env.ref(
            "mrp.block_reason1"
        )
        reason.loss_id = self.env.ref("mrp.category_quality")
        self.assertEqual(reason.loss_type, "quality")
        self.assertEqual(sibling.loss_type, "availability")

    def test_a_time_log_cannot_recategorize_every_reason(self):
        reason, sibling = self.env.ref("mrp.block_reason0") | self.env.ref(
            "mrp.block_reason1"
        )
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        start = fields.Datetime.now() - timedelta(hours=3)
        (log,) = self._timers(
            workorder, ("mrp.block_reason0", start, start + timedelta(minutes=30))
        )
        log.write({"loss_type": "quality"})
        self.env.invalidate_all()
        self.assertEqual(
            self.env.ref("mrp.category_availability").loss_type, "availability"
        )
        self.assertEqual((reason | sibling).mapped("loss_type"), ["availability"] * 2)

    def test_an_operation_numbered_zero_runs_first(self):
        production = self._confirmed_production(self.bom)
        production.button_plan()
        first = production.workorder_ids.filtered(
            lambda workorder: workorder.operation_id == self.first
        )
        second = production.workorder_ids - first
        self.assertEqual(first.sequence, 0)
        self.assertEqual(second.blocked_by_workorder_ids, first)
        self.assertFalse(first.blocked_by_workorder_ids)

    def _done_in(self, minutes):
        production = self._confirmed_production(self.bom)
        workorder = production.workorder_ids
        workorder.button_start()
        started = fields.Datetime.now() - timedelta(hours=3)
        workorder.time_ids.write(
            {"date_start": started, "date_end": started + timedelta(minutes=minutes)}
        )
        production.qty_producing = 1
        production.move_raw_ids.picked = True
        production.button_mark_done()

    def _timed_operation(self, workcenter, time_mode_batch=1):
        self.first.write(
            {
                "workcenter_id": workcenter.id,
                "time_mode": "auto",
                "time_mode_batch": time_mode_batch,
            }
        )
        self.bom.operation_ids = [Command.unlink(self.second.id)]

    def test_a_computed_cycle_nets_out_setup_and_cleanup(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Timed", "time_start": 10, "time_stop": 10}
        )
        self._timed_operation(workcenter)
        self.assertEqual(
            self._confirmed_production(self.bom).workorder_ids.duration_expected, 80
        )
        self._done_in(80)
        self.first.invalidate_recordset()
        self.assertEqual(self.first.time_cycle, 60)
        self.assertEqual(
            self._confirmed_production(self.bom).workorder_ids.duration_expected, 80
        )

    def test_a_computed_cycle_nets_out_efficiency(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Half speed", "time_start": 0, "time_stop": 0}
        )
        workcenter.time_efficiency = 50
        self._timed_operation(workcenter)
        self.assertEqual(
            self._confirmed_production(self.bom).workorder_ids.duration_expected, 120
        )
        self._done_in(120)
        self.first.invalidate_recordset()
        self.assertEqual(self.first.time_cycle, 60)
        self.assertEqual(
            self._confirmed_production(self.bom).workorder_ids.duration_expected, 120
        )

    def test_the_form_follows_the_history_window(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Timed", "time_start": 0, "time_stop": 0}
        )
        self._timed_operation(workcenter, time_mode_batch=10)
        self._done_in(30)
        self._done_in(90)
        with Form(self.first) as form:
            self.assertEqual(form.time_total, 60)
            form.time_mode_batch = 1
            self.assertEqual(
                form.time_total,
                90,
                "averaging only the last work order shows the last one's time",
            )

    def test_a_kit_operation_keeps_its_own_place_in_the_routing(self):
        kit, kit_component = self.env["product.product"].create(
            [{"name": "Kit"}, {"name": "Kit component", "is_storable": True}]
        )
        kit_bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": kit_component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {"name": "kit step", "workcenter_id": self.workcenter_2.id}
                    )
                ],
            }
        )
        kit_bom.bom_line_ids.operation_id = kit_bom.operation_ids
        self.bom.bom_line_ids = [
            Command.create({"product_id": kit.id, "product_qty": 1})
        ]
        production = self._confirmed_production(self.bom)
        production.button_plan()
        kit_workorder = production.workorder_ids.filtered(
            lambda workorder: workorder.operation_id == kit_bom.operation_ids
        )
        self.assertEqual(kit_workorder.sequence, kit_bom.operation_ids.sequence)
        self.assertEqual(
            sorted(production.workorder_ids.mapped("sequence")),
            [0, 1, kit_bom.operation_ids.sequence],
        )
        self.assertEqual(kit_workorder.move_raw_ids.product_id, kit_component)

    def _local(self, workorder, day, hour, minute=0):
        zone = ZoneInfo(workorder.workcenter_id.resource_id.tz or "UTC")
        return (
            datetime(2026, 9, day, hour, minute, tzinfo=zone)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

    def test_a_blocked_night_costs_no_machine_time(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        workorder.workcenter_id.costs_hour = 60
        other = self.user_mrp_user
        self._timers(
            workorder,
            (
                "mrp.block_reason7",
                self._local(workorder, 21, 8),
                self._local(workorder, 21, 9),
                self.env.user,
            ),
            (
                "mrp.block_reason7",
                self._local(workorder, 21, 8),
                self._local(workorder, 21, 9),
                other,
            ),
            (
                "mrp.block_reason0",
                self._local(workorder, 21, 17),
                self._local(workorder, 22, 8),
                self.env.user,
            ),
        )
        self.assertEqual(workorder.duration, 60)
        self.assertEqual(workorder._get_cost(), 60)

    def test_work_and_a_blockage_at_once_occupy_the_machine_once(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        workorder.workcenter_id.costs_hour = 60
        self._timers(
            workorder,
            (
                "mrp.block_reason7",
                self._local(workorder, 21, 10),
                self._local(workorder, 21, 11),
                self.env.user,
            ),
            (
                "mrp.block_reason0",
                self._local(workorder, 21, 10, 30),
                self._local(workorder, 21, 11, 30),
                self.env.user,
            ),
        )
        self.assertEqual(workorder.duration, 90)
        self.assertEqual(workorder._get_cost(), 90)

    def test_the_wip_cutoff_counts_timers_closed_by_the_date(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        workorder.workcenter_id.costs_hour = 60
        self._timers(
            workorder,
            (
                "mrp.block_reason7",
                self._local(workorder, 21, 8),
                self._local(workorder, 21, 9),
                self.env.user,
            ),
            (
                "mrp.block_reason7",
                self._local(workorder, 21, 10),
                self._local(workorder, 21, 11),
                self.env.user,
            ),
        )
        self.assertEqual(workorder._get_cost(self._local(workorder, 21, 9, 30)), 60)
        self.assertEqual(workorder._get_cost(), 120)

    def test_two_operators_in_one_hour_are_one_productive_hour(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        self._timers(
            workorder,
            *(
                (
                    "mrp.block_reason7",
                    fields.Datetime.now() - timedelta(hours=3),
                    fields.Datetime.now() - timedelta(hours=2),
                    user,
                )
                for user in (self.env.user, self.user_mrp_user)
            ),
        )
        workcenter = workorder.workcenter_id
        workcenter.invalidate_recordset()
        self.assertEqual(workorder.duration, 60)
        self.assertEqual(
            workcenter.productive_time,
            workorder.duration / 60,
            "the work center was productive for the hour its work order occupied it",
        )

    def test_marking_done_logs_the_expected_time_when_none_was_measured(self):
        workorder = self._confirmed_production(self.bom).workorder_ids[0]
        self._timers(
            workorder,
            (
                "mrp.block_reason0",
                self._local(workorder, 20, 22),
                self._local(workorder, 20, 23),
                self.env.user,
            ),
        )
        self.assertEqual(workorder.duration, 0)
        MrpWorkorder.action_mark_as_done(workorder)
        self.assertEqual(
            workorder.duration,
            workorder.duration_expected,
            "a blockage outside working hours measures nothing, so the order "
            "is logged at its expected time",
        )
