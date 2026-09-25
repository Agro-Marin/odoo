from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import Command, fields
from odoo.tests import Form, tagged

from .common import TestMrpCommon


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
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": name,
                            "workcenter_id": cls.workcenter_2.id,
                            "time_cycle_manual": 60,
                            "sequence": sequence,
                        }
                    )
                    for sequence, name in enumerate(("first", "second"))
                ],
            }
        )
        cls.first, cls.second = cls.bom.operation_ids.sorted("sequence")

    def _confirmed(self):
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = self.bom
        form.product_qty = 1
        production = form.save()
        production.action_confirm()
        return production

    def _timers(self, workorder, *rows, start=None):
        start = start or fields.Datetime.now() - timedelta(hours=3)
        return self.env["mrp.workcenter.productivity"].create(
            [
                {
                    "workorder_id": workorder.id,
                    "workcenter_id": workorder.workcenter_id.id,
                    "loss_id": self.env.ref(loss).id,
                    "date_start": start + timedelta(minutes=offset),
                    "date_end": start + timedelta(minutes=offset + minutes)
                    if minutes
                    else False,
                }
                for loss, offset, minutes in rows
            ]
        )

    def test_overlapping_reasons_of_one_category_count_once(self):
        workorder = self._confirmed().workorder_ids[0]
        zone = ZoneInfo(workorder.workcenter_id.resource_id.tz or "UTC")
        monday = (
            datetime(2026, 9, 21, 9, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
        )
        self._timers(
            workorder,
            ("mrp.block_reason0", 0, 60),
            ("mrp.block_reason1", 30, 60),
            start=monday,
        )
        merged = workorder.workcenter_id._get_working_minutes_batch(
            [(monday, monday + timedelta(minutes=90))]
        )[0]
        self.assertGreater(merged, 0)
        self.env.flush_all()
        workorder.invalidate_recordset()
        self.assertEqual(workorder.duration, merged)

    def test_the_deviation_follows_a_written_duration(self):
        workorder = self._confirmed().workorder_ids[0]
        self.assertEqual(workorder.duration_expected, 60)
        workorder.duration = 30
        self.env.flush_all()
        workorder.invalidate_recordset()
        self.assertEqual(workorder.duration, 30)
        self.assertEqual(workorder.duration_percent, 50)

    def test_lowering_the_duration_keeps_a_running_timer(self):
        workorder = self._confirmed().workorder_ids[0]
        closed, running = self._timers(
            workorder,
            ("mrp.block_reason7", 0, 60),
            ("mrp.block_reason7", 90, 0),
        )
        workorder.duration = 50
        self.assertTrue(running.exists())
        self.assertTrue(closed.exists())

    def test_setting_to_do_keeps_a_blocked_order_blocked(self):
        production = self._confirmed()
        production.button_plan()
        _first, second = production.workorder_ids.sorted(
            lambda workorder: workorder.operation_id.sequence
        )
        self.assertEqual(second.state, "blocked")
        second.set_state("ready")
        self.assertEqual(second.state, "blocked")

    def test_replanning_follows_the_current_dependencies(self):
        self.bom.allow_operation_dependencies = True
        self.first.blocked_by_operation_ids = self.second
        production = self._confirmed()
        production.button_plan()
        production.button_unplan()
        self.bom.allow_operation_dependencies = False
        production.button_plan()
        first, second = production.workorder_ids.sorted(
            lambda workorder: workorder.operation_id.sequence
        )
        self.assertFalse(first.blocked_by_workorder_ids)
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
        workorder = self._confirmed().workorder_ids[0]
        (log,) = self._timers(workorder, ("mrp.block_reason0", 0, 30))
        log.write({"loss_type": "quality"})
        self.env.invalidate_all()
        self.assertEqual(
            self.env.ref("mrp.category_availability").loss_type, "availability"
        )
        self.assertEqual((reason | sibling).mapped("loss_type"), ["availability"] * 2)

    def test_an_operation_numbered_zero_runs_first(self):
        production = self._confirmed()
        production.button_plan()
        first = production.workorder_ids.filtered(
            lambda workorder: workorder.operation_id == self.first
        )
        second = production.workorder_ids - first
        self.assertEqual(first.sequence, 0)
        self.assertEqual(second.blocked_by_workorder_ids, first)
        self.assertFalse(first.blocked_by_workorder_ids)

    def test_a_computed_cycle_nets_out_setup_and_cleanup(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Timed", "time_start": 10, "time_stop": 10}
        )
        self.first.write(
            {
                "workcenter_id": workcenter.id,
                "time_mode": "auto",
                "time_mode_batch": 1,
            }
        )
        self.bom.operation_ids = [Command.unlink(self.second.id)]
        production = self._confirmed()
        workorder = production.workorder_ids
        self.assertEqual(workorder.duration_expected, 80)
        workorder.button_start()
        started = fields.Datetime.now() - timedelta(hours=3)
        workorder.time_ids.write(
            {"date_start": started, "date_end": started + timedelta(minutes=80)}
        )
        production.qty_producing = 1
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.first.invalidate_recordset()
        self.assertEqual(self.first.time_cycle, 60)
        self.assertEqual(self._confirmed().workorder_ids.duration_expected, 80)

    def test_a_computed_cycle_nets_out_efficiency(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Half speed", "time_start": 0, "time_stop": 0}
        )
        workcenter.time_efficiency = 50
        self.first.write(
            {"workcenter_id": workcenter.id, "time_mode": "auto", "time_mode_batch": 1}
        )
        self.bom.operation_ids = [Command.unlink(self.second.id)]
        production = self._confirmed()
        workorder = production.workorder_ids
        self.assertEqual(workorder.duration_expected, 120)
        workorder.button_start()
        started = fields.Datetime.now() - timedelta(hours=3)
        workorder.time_ids.write(
            {"date_start": started, "date_end": started + timedelta(minutes=120)}
        )
        production.qty_producing = 1
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.first.invalidate_recordset()
        self.assertEqual(self.first.time_cycle, 60)
        self.assertEqual(self._confirmed().workorder_ids.duration_expected, 120)
