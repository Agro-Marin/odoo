"""Regression tests for the resource hardening pass.

Each class pins one defect that the previous suite did not cover.  The
docstrings state the *observed wrong behaviour*, so a future change that
reintroduces it fails with an explanation rather than a bare assertion.
"""

from datetime import date, datetime, timedelta

from pytz import timezone, utc

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestFlexibleAttendanceSynthesis(TransactionCase):
    """Pins the synthesized schedule of a flexible calendar.

    The fill is greedy from the window start on purpose (a Tue→Sat question
    credits five working days), which also means the result is not additive
    across sub-windows.  Both properties are asserted here so that a future
    change to either is a deliberate, visible decision rather than a silent
    drift — switching to calendar-week anchoring, for instance, shortens every
    mid-week leave and breaks ``hr_holidays``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible 40h",
                "schedule_type": "flexible",
                "hours_per_week": 40,
                "hours_per_day": 8,
                "tz": "UTC",
            }
        )

    def _hours(self, start, end):
        return self.calendar.get_work_hours_count(
            utc.localize(start), utc.localize(end), compute_leaves=False
        )

    def test_seven_day_window_yields_the_weekly_budget(self):
        for offset in range(7):
            start = datetime(2025, 3, 3) + timedelta(days=offset)
            with self.subTest(start=start.date()):
                self.assertAlmostEqual(
                    self._hours(start, start + timedelta(days=7)), 40.0, places=2
                )

    def test_fill_is_greedy_from_the_window_start(self):
        """A mid-week window is credited its own days, not the week's leftovers.

        ``hr_holidays.test_undefined_working_hours`` depends on this: a
        Tue→Sat request for a 40h/week flexible employee is five days off, and
        anchoring the budget on the calendar Monday would silently make it
        four.
        """
        tuesday, sunday = datetime(2025, 3, 4), datetime(2025, 3, 9)
        self.assertAlmostEqual(self._hours(tuesday, sunday), 40.0, places=2)

    def test_not_additive_across_sub_windows(self):
        """Documents the known cost of the greedy fill.

        Each sub-window restarts the weekly budget, so summing parts exceeds
        the whole.  Consumers that partition a period (two adjacent
        reservations covering one week, a month-by-month report) over-count,
        and must ask once over the full range instead.
        """
        monday, thursday = datetime(2025, 3, 3), datetime(2025, 3, 6)
        next_monday = datetime(2025, 3, 10)
        whole = self._hours(monday, next_monday)
        parts = self._hours(monday, thursday) + self._hours(thursday, next_monday)
        self.assertAlmostEqual(whole, 40.0, places=2)
        self.assertGreater(
            parts,
            whole,
            "greedy per-window filling is expected to over-count when split; "
            "if this now holds, the anchoring changed — check hr_holidays",
        )

    def test_dst_transition_keeps_one_block_per_day(self):
        """Day stepping must not drift across a DST switch."""
        brussels = timezone("Europe/Brussels")
        calendar = self.env["resource.calendar"].create(
            {
                "name": "Flexible Brussels",
                "schedule_type": "flexible",
                "hours_per_week": 40,
                "hours_per_day": 8,
                "tz": "Europe/Brussels",
            }
        )
        start = brussels.localize(datetime(2025, 3, 24))
        end = brussels.localize(datetime(2025, 4, 7))
        intervals = calendar._flexible_attendance_intervals(start, end, brussels)
        days = [interval[0].date() for interval in intervals]
        self.assertEqual(
            len(days), len(set(days)), "a day was allocated twice across the DST switch"
        )


class TestFlexibleWeekKeyIsDeterministic(TransactionCase):
    """The flexible weekly budget must not depend on a display preference.

    The bucket used to come from the acting user's locale, so the very same
    booking stored 48h under a Sunday-start language and 40h under a
    Monday-start one.  Worse, the producer keyed off ``res.lang.week_start``
    while ``hr_holidays`` keyed off babel's ``locale.first_week_day`` — two
    different sources that only coincide by accident, and when they diverge
    the leave hours stop being subtracted at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible 40h",
                "schedule_type": "flexible",
                "hours_per_week": 40,
                "hours_per_day": 8,
                "tz": "UTC",
            }
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Flexible worker", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.lang = cls.env["res.lang"].search(
            [("code", "=", cls.env.user.lang or "en_US")], limit=1
        )

    def _allocated_hours_with_week_start(self, week_start):
        self.lang.week_start = week_start
        self.env.invalidate_all()
        return (
            self.env["resource.reservation"]
            .create(
                {
                    "name": f"booking-{week_start}",
                    "resource_id": self.resource.id,
                    "date_start": datetime(2025, 3, 3),
                    "date_end": datetime(2025, 3, 10),
                }
            )
            .allocated_hours
        )

    def test_allocated_hours_ignores_week_start(self):
        sunday_start = self._allocated_hours_with_week_start("7")
        monday_start = self._allocated_hours_with_week_start("1")
        self.assertEqual(
            sunday_start,
            monday_start,
            "allocated_hours must not depend on res.lang.week_start",
        )

    def test_week_key_is_iso_and_locale_free(self):
        Resource = self.env["resource.resource"]
        # Sun 2025-03-09 and Mon 2025-03-10 are different ISO weeks; a
        # Sunday-anchored bucket would group them together.
        self.assertEqual(Resource._flexible_week_key(date(2025, 3, 9)), (2025, 10))
        self.assertEqual(Resource._flexible_week_key(date(2025, 3, 10)), (2025, 11))
        for week_start in ("1", "7"):
            self.lang.week_start = week_start
            self.env.invalidate_all()
            with self.subTest(week_start=week_start):
                self.assertEqual(
                    Resource._flexible_week_key(date(2025, 3, 9)), (2025, 10)
                )

    def test_valid_work_intervals_budget_ignores_week_start(self):
        start, end = (
            utc.localize(datetime(2025, 3, 3)),
            utc.localize(datetime(2025, 3, 10)),
        )
        results = []
        for week_start in ("7", "1"):
            self.lang.week_start = week_start
            self.env.invalidate_all()
            intervals, per_day, per_week = (
                self.resource._get_flexible_resource_valid_work_intervals(start, end)
            )
            results.append(
                self.resource._get_flexible_resource_work_hours(
                    intervals[self.resource.id],
                    per_day[self.resource.id],
                    per_week[self.resource.id],
                )
            )
        self.assertEqual(results[0], results[1])


class TestUnavailableIntervalsFlexible(TransactionCase):
    """Flexible resources must always appear in the unavailability mapping.

    The key was only written when the resource had leaves, so a flexible
    resource with a clean calendar vanished from the result: the singular
    helper raised KeyError, and gantt consumers reading it through
    ``.get(resource.id, company_leaves)`` silently painted the *company's*
    unavailability onto an available resource.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible",
                "schedule_type": "flexible",
                "hours_per_week": 40,
                "hours_per_day": 8,
                "tz": "UTC",
            }
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Flexible worker", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.start = utc.localize(datetime(2025, 3, 3))
        cls.end = utc.localize(datetime(2025, 3, 8))

    def test_batch_contains_resource_without_leaves(self):
        result = self.calendar._unavailable_intervals_batch(
            self.start, self.end, self.resource
        )
        self.assertIn(
            self.resource.id,
            result,
            "a flexible resource with no leaves must still be reported",
        )
        self.assertEqual(result[self.resource.id], [])

    def test_singular_helper_does_not_raise(self):
        self.assertEqual(
            self.calendar._unavailable_intervals(self.start, self.end, self.resource),
            [],
        )

    def test_resource_level_helper_reports_every_resource(self):
        self.assertIn(
            self.resource.id,
            self.resource._get_unavailable_intervals(self.start, self.end),
        )

    def test_leaves_are_still_reported(self):
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Day off",
                "calendar_id": self.calendar.id,
                "resource_id": self.resource.id,
                "date_from": datetime(2025, 3, 5),
                "date_to": datetime(2025, 3, 5, 23, 59),
            }
        )
        result = self.calendar._unavailable_intervals_batch(
            self.start, self.end, self.resource
        )
        self.assertTrue(result[self.resource.id])


class TestPlanDaysHonoursResource(TransactionCase):
    """``plan_days`` accepted no resource, so resource leaves were invisible."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env.ref("resource.resource_calendar_std")
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Planned", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.env["resource.calendar.leaves"].create(
            {
                "name": "Away all week",
                "calendar_id": cls.calendar.id,
                "resource_id": cls.resource.id,
                "date_from": datetime(2025, 4, 7),
                "date_to": datetime(2025, 4, 11, 23, 59),
            }
        )

    def test_resource_leave_pushes_the_plan_out(self):
        start = utc.localize(datetime(2025, 4, 7, 8))
        without = self.calendar.plan_days(3, start, compute_leaves=True)
        with_resource = self.calendar.plan_days(
            3, start, compute_leaves=True, resource=self.resource
        )
        self.assertTrue(with_resource)
        self.assertGreater(
            with_resource,
            without,
            "the resource's own leave must delay the planned end",
        )
        self.assertGreaterEqual(
            with_resource.date(),
            datetime(2025, 4, 14).date(),
            "planning must skip the week the resource is on leave",
        )


class TestReservationCompanyIntegrity(TransactionCase):
    """A reservation must belong to the booked resource's company.

    It defaulted to ``env.company``, so a user acting in company B could book
    a company-A resource; the multi-company rule then hid that booking from
    company A, whose users saw the slot as free.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.ref("base.main_company")
        cls.company_b = cls.env["res.company"].create({"name": "Company B"})
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Company A machine",
                "company_id": cls.company_a.id,
                "calendar_id": cls.company_a.resource_calendar_id.id,
                "tz": "UTC",
            }
        )

    def test_company_follows_the_resource(self):
        reservation = (
            self.env["resource.reservation"]
            .with_company(self.company_b)
            .create(
                {
                    "name": "Booking",
                    "resource_id": self.resource.id,
                    "date_start": datetime(2025, 9, 9, 8),
                    "date_end": datetime(2025, 9, 9, 17),
                }
            )
        )
        self.assertEqual(reservation.company_id, self.company_a)

    def test_mismatched_company_is_rejected(self):
        """``_check_company_auto`` turns the field flags into a real barrier."""
        with self.assertRaises(UserError):
            self.env["resource.reservation"].create(
                {
                    "name": "Cross company",
                    "resource_id": self.resource.id,
                    "company_id": self.company_b.id,
                    "date_start": datetime(2025, 9, 9, 8),
                    "date_end": datetime(2025, 9, 9, 17),
                }
            )


class TestHardEnforcementProtectsItsSlot(TransactionCase):
    """A 'hard' reservation is a claim against everyone, not just itself.

    Only the record being written used to be validated, so a *soft* booking —
    the default every consumer creates — could be created on, or rescheduled
    into, a hard reservation's window without complaint.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Protected machine",
                "calendar_id": cls.env.ref("resource.resource_calendar_std").id,
                "tz": "UTC",
            }
        )

    def _hard(self):
        return self.Reservation.create(
            {
                "name": "Maintenance",
                "resource_id": self.resource.id,
                "enforcement_mode": "hard",
                "date_start": datetime(2025, 6, 2, 8),
                "date_end": datetime(2025, 6, 2, 17),
            }
        )

    def test_soft_cannot_be_created_over_a_hard_slot(self):
        self._hard()
        with self.assertRaises(ValidationError):
            self.Reservation.create(
                {
                    "name": "Ordinary task",
                    "resource_id": self.resource.id,
                    "date_start": datetime(2025, 6, 2, 10),
                    "date_end": datetime(2025, 6, 2, 14),
                }
            )

    def test_soft_cannot_be_moved_onto_a_hard_slot(self):
        self._hard()
        mover = self.Reservation.create(
            {
                "name": "Ordinary task",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 6, 3, 8),
                "date_end": datetime(2025, 6, 3, 17),
            }
        )
        with self.assertRaises(ValidationError):
            mover.write(
                {
                    "date_start": datetime(2025, 6, 2, 10),
                    "date_end": datetime(2025, 6, 2, 14),
                }
            )

    def test_partial_allocations_still_fit(self):
        """The claim is cumulative, not exclusive: 50% + 50% remains legal."""
        self.Reservation.create(
            {
                "name": "Half hard",
                "resource_id": self.resource.id,
                "enforcement_mode": "hard",
                "allocated_percentage": 50.0,
                "date_start": datetime(2025, 6, 4, 8),
                "date_end": datetime(2025, 6, 4, 17),
            }
        )
        other = self.Reservation.create(
            {
                "name": "Other half",
                "resource_id": self.resource.id,
                "allocated_percentage": 50.0,
                "date_start": datetime(2025, 6, 4, 8),
                "date_end": datetime(2025, 6, 4, 17),
            }
        )
        self.assertTrue(other.id)

    def test_adjacent_booking_is_not_a_conflict(self):
        self._hard()
        adjacent = self.Reservation.create(
            {
                "name": "Right after",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 6, 2, 17),
                "date_end": datetime(2025, 6, 2, 19),
            }
        )
        self.assertTrue(adjacent.id)

    def test_archived_hard_does_not_block(self):
        blocker = self._hard()
        blocker.active = False
        allowed = self.Reservation.create(
            {
                "name": "Now free",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 6, 2, 10),
                "date_end": datetime(2025, 6, 2, 14),
            }
        )
        self.assertTrue(allowed.id)


class TestOverlapSweep(TransactionCase):
    """The sweep must stay correct after being rewritten as a boundary walk."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Swept",
                "calendar_id": cls.env.ref("resource.resource_calendar_std").id,
                "tz": "UTC",
            }
        )

    def _make(self, day, hour_from, hour_to, pct=100.0):
        return self.Reservation.create(
            {
                "name": f"r{day}-{hour_from}",
                "resource_id": self.resource.id,
                "allocated_percentage": pct,
                "date_start": datetime(2025, 1, day, hour_from),
                "date_end": datetime(2025, 1, day, hour_to),
            }
        )

    def test_cumulative_three_way_conflict(self):
        """3 x 50% = 150% conflicts even though no single pair exceeds 100%."""
        first = self._make(6, 8, 17, pct=50.0)
        self._make(6, 8, 17, pct=50.0)
        self._make(6, 8, 17, pct=50.0)
        first.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(first.schedule_overlap_count, 2)

    def test_no_conflict_when_within_capacity(self):
        first = self._make(7, 8, 17, pct=50.0)
        self._make(7, 8, 17, pct=50.0)
        first.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(first.schedule_overlap_count, 0)

    def test_adjacent_intervals_do_not_overlap(self):
        first = self._make(8, 8, 12)
        self._make(8, 12, 17)
        first.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(first.schedule_overlap_count, 0)

    def test_zero_length_reservation_covers_nothing(self):
        first = self._make(9, 8, 17)
        self._make(9, 10, 10)
        first.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(first.schedule_overlap_count, 0)

    def test_distant_history_is_not_scanned(self):
        """Old bookings outside the window must not enter the computation."""
        self.Reservation.create(
            [
                {
                    "name": f"ancient{index}",
                    "resource_id": self.resource.id,
                    "date_start": datetime(2000, 1, 1, 8) + timedelta(days=index),
                    "date_end": datetime(2000, 1, 1, 17) + timedelta(days=index),
                }
                for index in range(5)
            ]
        )
        recent = self._make(10, 8, 17)
        recent.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(recent.schedule_overlap_count, 0)


class TestAllocatedHoursBatching(TransactionCase):
    """Batching must not change the numbers it produces."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env.ref("resource.resource_calendar_std")

    def test_batch_matches_one_by_one(self):
        resources = self.env["resource.resource"].create(
            [
                {"name": f"R{index}", "calendar_id": self.calendar.id, "tz": "UTC"}
                for index in range(5)
            ]
        )
        vals = [
            {
                "name": f"b{index}",
                "resource_id": resource.id,
                "date_start": datetime(2025, 3, 3, 9) + timedelta(days=index),
                "date_end": datetime(2025, 3, 3, 17) + timedelta(days=index),
            }
            for index, resource in enumerate(resources)
        ]
        batched = self.env["resource.reservation"].create(vals)
        one_by_one = [
            self.env["resource.reservation"].create(
                dict(entry, name=f"{entry['name']}s")
            )
            for entry in vals
        ]
        self.assertEqual(
            batched.mapped("allocated_hours"),
            [record.allocated_hours for record in one_by_one],
        )

    def test_percentage_is_applied(self):
        resource = self.env["resource.resource"].create(
            {"name": "Half", "calendar_id": self.calendar.id, "tz": "UTC"}
        )
        full = self.env["resource.reservation"].create(
            {
                "name": "full",
                "resource_id": resource.id,
                "date_start": datetime(2025, 3, 3, 8),
                "date_end": datetime(2025, 3, 3, 17),
            }
        )
        half = self.env["resource.reservation"].create(
            {
                "name": "half",
                "resource_id": resource.id,
                "allocated_percentage": 50.0,
                "date_start": datetime(2025, 3, 4, 8),
                "date_end": datetime(2025, 3, 4, 17),
            }
        )
        self.assertAlmostEqual(half.allocated_hours, full.allocated_hours / 2, places=2)

    def test_undated_reservation_is_zero(self):
        resource = self.env["resource.resource"].create(
            {"name": "Undated", "calendar_id": self.calendar.id, "tz": "UTC"}
        )
        reservation = self.env["resource.reservation"].create(
            {"name": "undated", "resource_id": resource.id}
        )
        self.assertEqual(reservation.allocated_hours, 0.0)


class TestLeaveSecurityRule(TransactionCase):
    """Employees may only manage their *own* time off.

    The rule matched `user_id in [False, user.id]` after already excluding
    global records, so every resource without a user account — machines,
    rooms, unlinked employees — was writable by any internal user.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = new_test_user(cls.env, login="resource_employee")
        cls.machine = cls.env["resource.resource"].create(
            {
                "name": "CNC machine",
                "resource_type": "material",
                "calendar_id": cls.env.ref("resource.resource_calendar_std").id,
                "tz": "UTC",
            }
        )
        cls.machine_leave = cls.env["resource.calendar.leaves"].create(
            {
                "name": "Maintenance",
                "resource_id": cls.machine.id,
                "date_from": datetime(2025, 7, 1),
                "date_to": datetime(2025, 7, 2),
            }
        )

    def test_employee_cannot_write_machine_downtime(self):
        with self.assertRaises(AccessError):
            self.machine_leave.with_user(self.employee).write({"name": "hijacked"})

    def test_employee_cannot_unlink_machine_downtime(self):
        with self.assertRaises(AccessError):
            self.machine_leave.with_user(self.employee).unlink()

    def test_employee_cannot_create_machine_downtime(self):
        with self.assertRaises(AccessError):
            self.env["resource.calendar.leaves"].with_user(self.employee).create(
                {
                    "name": "Fabricated outage",
                    "resource_id": self.machine.id,
                    "date_from": datetime(2025, 8, 1),
                    "date_to": datetime(2025, 8, 30),
                }
            )

    def test_employee_can_still_read_machine_downtime(self):
        self.machine_leave.with_user(self.employee).read(["name"])

    def test_employee_manages_own_time_off(self):
        own_resource = self.env["resource.resource"].create(
            {
                "name": "Employee resource",
                "user_id": self.employee.id,
                "calendar_id": self.env.ref("resource.resource_calendar_std").id,
                "tz": "UTC",
            }
        )
        leave = (
            self.env["resource.calendar.leaves"]
            .with_user(self.employee)
            .create(
                {
                    "name": "My day off",
                    "resource_id": own_resource.id,
                    "date_from": datetime(2025, 7, 10),
                    "date_to": datetime(2025, 7, 10, 23, 59),
                }
            )
        )
        leave.write({"name": "My renamed day off"})
        leave.unlink()

    def test_manager_still_manages_machine_downtime(self):
        manager = new_test_user(
            self.env, login="resource_manager", groups="base.group_erp_manager"
        )
        self.machine_leave.with_user(manager).write({"name": "Rescheduled maintenance"})
        self.assertEqual(self.machine_leave.name, "Rescheduled maintenance")
