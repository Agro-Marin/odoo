from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import Form, tagged

from .common import TestMrpCommon
from odoo.addons.mrp.models.mrp_workorder import MrpWorkorder


class WorkorderSchedulingCase(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dozen = cls.env.ref("uom.product_uom_dozen")
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "UTC 08-12 13-17",
                "tz": "UTC",
                "attendance_ids": [
                    Command.create(
                        {
                            "name": f"{day} {hour_from}-{hour_to}",
                            "dayofweek": str(day),
                            "hour_from": hour_from,
                            "hour_to": hour_to,
                            "day_period": period,
                        }
                    )
                    for day in range(5)
                    for hour_from, hour_to, period in (
                        (8, 12, "morning"),
                        (13, 17, "afternoon"),
                    )
                ],
            }
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {
                "name": "Bangkok press",
                "resource_calendar_id": cls.calendar.id,
                "tz": "Asia/Bangkok",
                "time_start": 0,
                "time_stop": 0,
                "time_efficiency": 100,
            }
        )
        cls.finished, cls.component = cls.env["product.product"].create(
            [
                {"name": "Scheduled", "is_storable": True},
                {"name": "Scheduled part", "is_storable": True},
            ]
        )

    @classmethod
    def _bom(cls, *names, product_qty=1, workcenter=None):
        return cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": product_qty,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": name,
                            "workcenter_id": (workcenter or cls.workcenter).id,
                            "time_cycle_manual": 60,
                            "sequence": sequence,
                        }
                    )
                    for sequence, name in enumerate(names)
                ],
            }
        )

    def _confirmed(self, bom, qty=1, unit=None):
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = bom
        form.product_qty = qty
        if unit:
            form.product_uom_id = unit
        production = form.save()
        production.action_confirm()
        return production

    def _at(self, *args, workcenter=None):
        zone = ZoneInfo((workcenter or self.workcenter).resource_id.tz or "UTC")
        return datetime(*args, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)


@tagged("post_install", "-at_install")
class TestWorkorderResourceZone(WorkorderSchedulingCase):
    def test_moving_a_work_order_ends_it_in_the_work_centers_zone(self):
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.write({"date_start": self._at(2030, 1, 7, 8)})
        self.assertEqual(
            workorder.date_end,
            self._at(2030, 1, 7, 9),
            "an hour of work from 08:00 where the press stands ends at 09:00 there",
        )

    def test_resizing_a_work_order_measures_the_work_centers_hours(self):
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.write(
            {
                "date_start": self._at(2030, 1, 7, 8),
                "date_end": self._at(2030, 1, 7, 9),
                "duration_expected": 60,
            }
        )
        workorder.write({"date_end": self._at(2030, 1, 7, 10)})
        self.assertEqual(workorder.duration_expected, 120)

    def test_the_work_centers_own_leave_pushes_the_end(self):
        self.env["resource.schedule.exception"].create(
            {
                "name": "Press maintenance",
                "calendar_id": self.calendar.id,
                "resource_id": self.workcenter.resource_id.id,
                "date_from": self._at(2030, 1, 7, 8),
                "date_to": self._at(2030, 1, 7, 12),
            }
        )
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.write({"date_start": self._at(2030, 1, 7, 8)})
        self.assertEqual(workorder.date_end, self._at(2030, 1, 7, 14))


@tagged("post_install", "-at_install")
class TestWorkorderTimerClose(WorkorderSchedulingCase):
    def _open_timer(self, workorder, loss_xmlid, minutes_ago):
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": workorder.id,
                "workcenter_id": workorder.workcenter_id.id,
                "loss_id": self.env.ref(loss_xmlid).id,
                "date_start": fields.Datetime.now() - timedelta(minutes=minutes_ago),
            }
        )

    def test_a_work_order_without_expectation_stays_productive(self):
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.duration_expected = 0
        timer = self._open_timer(workorder, "mrp.block_reason7", 60)
        workorder.end_all()
        self.assertEqual(
            (workorder.time_ids.mapped("loss_type"), timer.loss_type),
            (["productive"], "productive"),
            "no expectation means no overrun: _prepare_timeline_vals agrees",
        )

    def test_closing_keeps_a_blocking_reason(self):
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.duration_expected = 30
        start = fields.Datetime.now() - timedelta(hours=5)
        self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": workorder.id,
                "workcenter_id": workorder.workcenter_id.id,
                "loss_id": self.env.ref("mrp.block_reason7").id,
                "date_start": start,
                "date_end": start + timedelta(minutes=120),
            }
        )
        blocked = self._open_timer(workorder, "mrp.block_reason0", 10)
        workorder.end_all()
        self.assertEqual(
            (blocked.loss_id, len(workorder.time_ids)),
            (self.env.ref("mrp.block_reason0"), 2),
            "an availability row is not a performance loss and is not split",
        )


@tagged("post_install", "-at_install")
class TestWorkorderStartStop(WorkorderSchedulingCase):
    @freeze_time("2030-01-07 03:00:00")
    def test_starting_a_late_order_keeps_its_length(self):
        for planned_start in (self._at(2030, 1, 7, 8), self._at(2030, 1, 7, 9, 30)):
            with self.subTest(planned_start=planned_start):
                workorder = self._confirmed(self._bom("press")).workorder_ids
                workorder.write(
                    {
                        "date_start": planned_start,
                        "date_end": planned_start + timedelta(hours=1),
                        "duration_expected": 60,
                    }
                )
                workorder.button_start()
                self.assertEqual(
                    (workorder.date_start, workorder.date_end),
                    (self._at(2030, 1, 7, 10), self._at(2030, 1, 7, 11)),
                    "started at 10:00, an hour of work runs until 11:00",
                )

    def test_back_to_ready_stops_every_users_timer(self):
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.button_start()
        workorder.time_ids.unlink()
        Timer = self.env["mrp.workcenter.productivity"]
        timer_vals = [
            {
                "workorder_id": workorder.id,
                "workcenter_id": workorder.workcenter_id.id,
                "loss_id": self.env.ref("mrp.block_reason7").id,
                "user_id": user.id,
            }
            for user in (self.env.user, self.user_mrp_user)
        ]
        if "employee_id" in Timer._fields:
            for vals, user in zip(
                timer_vals, (self.env.user, self.user_mrp_user), strict=True
            ):
                vals["employee_id"] = (
                    self.env["hr.employee"].create({"name": user.name}).id
                )
        Timer.create(timer_vals)
        workorder.set_state("ready")
        self.assertEqual(
            (workorder.state, workorder.time_ids.filtered(lambda t: not t.date_end)),
            ("ready", self.env["mrp.workcenter.productivity"]),
            "a ready work order has nobody working on it",
        )

    def test_unblocking_two_orders_of_one_work_center(self):
        workorders = self._confirmed(self._bom("first", "second")).workorder_ids
        self.env["mrp.workcenter.productivity"].create(
            {
                "workcenter_id": self.workcenter.id,
                "loss_id": self.env.ref("mrp.block_reason0").id,
            }
        ).button_block()
        self.assertEqual(self.workcenter.working_state, "blocked")
        workorders.button_unblock()
        self.assertEqual(self.workcenter.working_state, "normal")


@tagged("post_install", "-at_install")
class TestWorkorderProductionDates(WorkorderSchedulingCase):
    def test_the_order_spans_its_earliest_start_and_latest_end(self):
        production = self._confirmed(self._bom("a", "b", "c"))
        first, second, third = production.workorder_ids.sorted("sequence")
        base = datetime(2030, 1, 7, 1)
        for index, workorder in enumerate((first, second, third)):
            workorder.write(
                {
                    "date_start": base + timedelta(hours=index),
                    "date_end": base + timedelta(hours=index + 1),
                    "duration_expected": 60,
                }
            )
        third.write(
            {
                "date_start": base + timedelta(hours=1),
                "date_end": base + timedelta(minutes=90),
                "duration_expected": 30,
            }
        )
        second.write(
            {
                "date_start": base - timedelta(hours=1),
                "date_end": base + timedelta(hours=2),
                "duration_expected": 180,
            }
        )
        self.assertEqual(
            (production.date_start, production.date_end),
            (base - timedelta(hours=1), base + timedelta(hours=2)),
            "the order runs from its earliest work order to its latest one, "
            "whatever their sequence",
        )


@tagged("post_install", "-at_install")
class TestWorkorderCapacityUnits(WorkorderSchedulingCase):
    def test_the_bom_batch_is_counted_in_the_orders_unit(self):
        bom = self._bom("press", product_qty=10)
        production = self._confirmed(bom, qty=1, unit=self.dozen)
        self.assertEqual(
            production.workorder_ids.duration_expected,
            120,
            "a dozen is 12 units: two batches of 10",
        )
        self.assertEqual(
            bom.operation_ids.with_context(quantity=1, unit=self.dozen).cycle_number,
            2,
        )

    def test_a_product_line_outranks_a_generic_line(self):
        self.env["mrp.workcenter.capacity"].create(
            [
                {
                    "workcenter_id": self.workcenter.id,
                    "product_uom_id": self.uom_unit.id,
                    "capacity": 5,
                },
                {
                    "workcenter_id": self.workcenter.id,
                    "product_id": self.finished.id,
                    "product_uom_id": self.dozen.id,
                    "capacity": 1,
                },
            ]
        )
        capacity, _setup, _cleanup = self.workcenter._get_capacity(
            self.finished, self.dozen
        )
        self.assertEqual(capacity, 1, "the press takes a dozen of this product")


@tagged("post_install", "-at_install")
class TestWorkorderAlternativeWithoutOperation(WorkorderSchedulingCase):
    @freeze_time("2030-01-07 09:00:00")
    def test_the_alternative_is_compared_at_its_own_duration(self):
        primary, slow = self.env["mrp.workcenter"].create(
            [
                {
                    "name": f"{name} press",
                    "resource_calendar_id": self.calendar.id,
                    "tz": "UTC",
                    "time_efficiency": efficiency,
                }
                for name, efficiency in (("Primary", 100), ("Slow", 50))
            ]
        )
        primary.alternative_workcenter_ids = slow
        self.env["resource.reservation"].create(
            {
                "name": "Busy",
                "resource_id": primary.resource_id.id,
                "date_start": datetime(2030, 1, 7, 9),
                "date_end": datetime(2030, 1, 7, 9, 30),
                "allocated_percentage": 100.0,
                "enforcement_mode": "soft",
            }
        )
        production = self._confirmed(self._bom())
        production.workorder_ids = [
            Command.create(
                {
                    "name": "Unrouted",
                    "workcenter_id": primary.id,
                    "duration_expected": 60,
                }
            )
        ]
        production.button_plan()
        workorder = production.workorder_ids
        self.assertEqual(
            (
                workorder.workcenter_id,
                workorder.duration_expected,
                workorder.date_start,
                workorder.date_end,
            ),
            (
                primary,
                60,
                datetime(2030, 1, 7, 9, 30),
                datetime(2030, 1, 7, 10, 30),
            ),
            "the slow press needs two hours and would end at 11:00, "
            "the primary one ends at 10:30",
        )


@tagged("post_install", "-at_install")
class TestWorkorderWorkcenterChange(WorkorderSchedulingCase):
    def test_the_reservation_follows_the_new_work_center(self):
        other = self.env["mrp.workcenter"].create(
            {"name": "Other press", "resource_calendar_id": self.calendar.id}
        )
        workorder = self._confirmed(self._bom("press")).workorder_ids
        workorder.write(
            {
                "date_start": self._at(2030, 1, 7, 8),
                "date_end": self._at(2030, 1, 7, 9),
                "duration_expected": 60,
            }
        )
        workorder.workcenter_id = other
        self.assertEqual(workorder.reservation_ids.resource_id, other.resource_id)


@tagged("post_install", "-at_install")
class TestWorkorderMarkAsDoneBatch(WorkorderSchedulingCase):
    def _statements_to_mark_done(self, operations):
        workorders = self._confirmed(
            self._bom(*(f"op {index}" for index in range(operations)))
        ).workorder_ids
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_statement_count
        MrpWorkorder.action_mark_as_done(workorders)
        self.env.flush_all()
        self.assertEqual(set(workorders.mapped("state")), {"done"})
        return self.env.cr.sql_statement_count - before

    def test_finishing_is_one_batch_not_one_per_work_order(self):
        two = self._statements_to_mark_done(2)
        eight = self._statements_to_mark_done(8)
        self.assertLess(
            eight - two,
            two,
            f"six more work orders cost {eight - two} statements on top of {two}",
        )
