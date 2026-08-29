import logging
import time
from datetime import date

from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, rrule

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install", "hr_attendance_perf")
class TestHrAttendancePerformance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.company_id = cls.env["res.company"].create(
            {"name": "Flower Corporation"}
        )
        cls.calendar_38h = cls.env["resource.calendar"].create(
            {
                "name": "Standard 38 hours/week",
                "tz": "Europe/Brussels",
                "company_id": False,
                "hours_per_day": 7.6,
                "attendance_ids": [
                    (5, 0, 0),
                    (
                        0,
                        0,
                        {
                            "name": "Monday Morning",
                            "dayofweek": "0",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Monday Lunch",
                            "dayofweek": "0",
                            "hour_from": 12,
                            "hour_to": 13,
                            "day_period": "lunch",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Monday Afternoon",
                            "dayofweek": "0",
                            "hour_from": 13,
                            "hour_to": 16.6,
                            "day_period": "afternoon",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Tuesday Morning",
                            "dayofweek": "1",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Tuesday Lunch",
                            "dayofweek": "1",
                            "hour_from": 12,
                            "hour_to": 13,
                            "day_period": "lunch",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Tuesday Afternoon",
                            "dayofweek": "1",
                            "hour_from": 13,
                            "hour_to": 16.6,
                            "day_period": "afternoon",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Wednesday Morning",
                            "dayofweek": "2",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Wednesday Lunch",
                            "dayofweek": "2",
                            "hour_from": 12,
                            "hour_to": 13,
                            "day_period": "lunch",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Wednesday Afternoon",
                            "dayofweek": "2",
                            "hour_from": 13,
                            "hour_to": 16.6,
                            "day_period": "afternoon",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Thursday Morning",
                            "dayofweek": "3",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Thursday Lunch",
                            "dayofweek": "3",
                            "hour_from": 12,
                            "hour_to": 13,
                            "day_period": "lunch",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Thursday Afternoon",
                            "dayofweek": "3",
                            "hour_from": 13,
                            "hour_to": 16.6,
                            "day_period": "afternoon",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Friday Morning",
                            "dayofweek": "4",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Friday Lunch",
                            "dayofweek": "4",
                            "hour_from": 12,
                            "hour_to": 13,
                            "day_period": "lunch",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Friday Afternoon",
                            "dayofweek": "4",
                            "hour_from": 13,
                            "hour_to": 16.6,
                            "day_period": "afternoon",
                        },
                    ),
                ],
            }
        )

        cls.ruleset = cls.env["hr.attendance.overtime.ruleset"].create(
            {
                "name": "Ruleset schedule quantity",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "Rule schedule quantity",
                            "base_off": "quantity",
                            "expected_hours_from_contract": True,
                            "quantity_period": "day",
                        }
                    ),
                ],
            }
        )

        employees = cls.env["hr.employee"].create(
            [
                {
                    "name": f"Employee {i}",
                    "sex": "male",
                    "birthday": "1982-08-01",
                    "country_id": cls.env.ref("base.us").id,
                    "wage": 5000.0,
                    "date_version": date.today() - relativedelta(months=2),
                    "contract_date_start": date.today() - relativedelta(months=2),
                    "contract_date_end": False,
                    "resource_calendar_id": cls.calendar_38h.id,
                    "ruleset_id": cls.ruleset.id,
                }
                for i in range(100)
            ]
        )
        for employee in employees:
            employee.create_version(
                {
                    "date_version": date.today() - relativedelta(months=1, days=15),
                    "wage": 5500,
                }
            )
            employee.create_version(
                {"date_version": date.today() - relativedelta(months=1), "wage": 6000}
            )

        vals = []
        for employee in employees:
            vals.extend(
                {
                    "employee_id": employee.id,
                    "check_in": day.replace(hour=8, minute=0),
                    "check_out": day.replace(hour=17, minute=36),
                }
                for day in rrule(
                    DAILY,
                    dtstart=date.today() - relativedelta(months=2),
                    until=date.today(),
                )
            )
        cls.attendances = cls.env["hr.attendance"].create(vals)

    def test_regenerate_overtime_line(self):
        t0 = time.time()
        with self.assertQueryCount(1700):
            self.ruleset.action_regenerate_overtimes()
        t1 = time.time()
        _logger.info(
            "Regenerated overtime for %s hr.attendance records in %s seconds.",
            len(self.attendances.ids),
            t1 - t0,
        )


@tagged("post_install", "-at_install")
class TestAttendanceComputeBatchCost(TransactionCase):
    """The employee computes must cost the same whatever the headcount.

    Both of these back the Attendances overview, which lists every employee, and
    both used to issue their query inside `for employee in self`. Measured at 40
    employees before the fix: `hours_today` 82 queries, `last_attendance_id` 47.

    The assertion is on the MARGINAL cost between two sizes, not an absolute
    count: an absolute pin at one size cannot see an N+1 at all, and it breaks
    on every unrelated query added elsewhere.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employees = cls.env["hr.employee"].create(
            [{"name": f"batch cost {i}"} for i in range(20)]
        )
        now = fields.Datetime.now()
        cls.env["hr.attendance"].create(
            [
                {
                    "employee_id": employee.id,
                    "check_in": now - relativedelta(hours=3),
                    "check_out": now - relativedelta(hours=1),
                }
                for employee in cls.employees
            ]
        )
        cls.env.flush_all()

    def _queries_for(self, compute_name, field_name, count):
        records = self.employees[:count]
        self.env.invalidate_all()
        records.mapped("attendance_ids")  # the dependency is not what is measured
        before = self.env.cr.sql_log_count
        if field_name is None:
            # `last_attendance_id` is stored, so reading it is a column read and
            # never runs the compute; the recompute path is the one with the
            # cost, and calling it is the only way to reach it. Non-stored
            # fields are read through instead -- a direct call runs outside
            # `Field.compute_value`'s `env.protecting`, so assigning re-enters
            # `__get__` per record and inflates the count with invocations no
            # reader pays for.
            getattr(records, compute_name)()
        else:
            records.mapped(field_name)
        return self.env.cr.sql_log_count - before

    def _assert_flat(self, compute_name, field_name=None):
        small = self._queries_for(compute_name, field_name, 2)
        large = self._queries_for(compute_name, field_name, 20)
        # Not equality: the small measurement runs first and warms caches the
        # large one reuses, so the large size can legitimately cost *less*. The
        # invariant is that it must not cost MORE -- that is what per-employee
        # querying looks like from outside.
        self.assertLessEqual(
            large,
            small,
            f"{compute_name} costs {large} queries for 20 employees against "
            f"{small} for 2: it is querying per employee. Two sizes rather than "
            f"one because a single size cannot tell a flat cost from a linear one, "
            f"and 2 rather than 1 so a warm cache cannot make it vacuous.",
        )

    def test_hours_today_does_not_query_per_employee(self):
        self._assert_flat("_compute_hours_today", field_name="hours_today")

    def test_last_attendance_id_does_not_query_per_employee(self):
        self._assert_flat("_compute_last_attendance_id")
