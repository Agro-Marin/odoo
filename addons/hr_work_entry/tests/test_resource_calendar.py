from datetime import UTC, date, datetime

from odoo.fields import Date
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged("work_entry")
class TestResourceCalendarWorkEntryType(TransactionCase):
    """The work entry type a calendar line carries decides which salary rule
    pays those hours, so it has to survive every way a calendar is born."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_calendar = cls.env.company.resource_calendar_id
        cls.type_attendance = cls.env.ref("hr_work_entry.work_entry_type_attendance")
        cls.type_overtime = cls.env.ref("hr_work_entry.work_entry_type_overtime")
        cls.type_home_working = cls.env.ref(
            "hr_work_entry.work_entry_type_home_working"
        )

    def _type_the_company_calendar(self):
        """Type the company's lines away from the field default.

        Two types, not one: a calendar that came back uniformly typed would
        also pass a single-type assertion by falling back to the default.
        """
        self.company_calendar.attendance_ids.work_entry_type_id = self.type_overtime
        fridays = self.company_calendar.attendance_ids.filtered(
            lambda attendance: attendance.dayofweek == "4"
        )
        fridays.work_entry_type_id = self.type_home_working
        self.assertNotEqual(
            self.type_overtime,
            self.type_attendance,
            "the fixture must not use the field's own default",
        )
        return [
            (attendance.dayofweek, attendance.day_period, attendance.work_entry_type_id)
            for attendance in self.company_calendar.attendance_ids
        ]

    def _assert_copied(self, calendar, expected):
        self.assertEqual(
            [
                (
                    attendance.dayofweek,
                    attendance.day_period,
                    attendance.work_entry_type_id,
                )
                for attendance in calendar.attendance_ids
            ],
            expected,
        )

    def test_create_keeps_company_work_entry_types(self):
        expected = self._type_the_company_calendar()
        calendar = self.env["resource.calendar"].create({"name": "Created"})
        self._assert_copied(calendar, expected)

    def test_form_keeps_company_work_entry_types(self):
        """The path the user actually walks: the new-calendar form.

        ``default_get`` seeds ``attendance_ids`` before ``_compute_attendance_ids``
        would, so the compute — which does copy the type — never runs here.
        """
        expected = self._type_the_company_calendar()
        form = Form(self.env["resource.calendar"])
        form.name = "From the form"
        self._assert_copied(form.save(), expected)


@tagged("work_entry")
class TestResourceCalendarLeaveTypedLine(TransactionCase):
    """A schedule line typed as time off is not work time.

    ``_get_global_attendances`` already says so -- it is what makes
    ``hours_per_week`` drop -- but the interval side had never been told, so
    the same calendar answered "32 hours a week" and "Friday is a working day".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Four days and a Friday off", "tz": "UTC"}
        )
        cls.unpaid = cls.env.ref("hr_work_entry.work_entry_type_unpaid_leave")
        cls.fridays = cls.calendar.attendance_ids.filtered(
            lambda attendance: attendance.dayofweek == "4"
        )
        # A full Monday-to-Sunday week, so the assertions read as weekdays.
        cls.monday = datetime(2026, 8, 31, tzinfo=UTC)
        cls.sunday = datetime(2026, 9, 6, 23, 59, tzinfo=UTC)
        cls.friday = date(2026, 9, 4)

    def _unusual_days(self):
        return self.calendar._get_unusual_days(self.monday, self.sunday)

    def _worked_dates(self, **kwargs):
        return {
            interval[0].date()
            for interval in self.calendar._work_intervals_batch(
                self.monday, self.sunday, **kwargs
            )[False]
        }

    def test_leave_typed_line_stops_being_work_time(self):
        self.assertFalse(self._unusual_days()[Date.to_string(self.friday)])
        self.assertIn(self.friday, self._worked_dates())

        self.fridays.work_entry_type_id = self.unpaid
        self.calendar.invalidate_recordset()

        self.assertEqual(
            self.calendar._get_hours_per_week(),
            32.0,
            "the hours side already excluded the line",
        )
        self.assertTrue(
            self._unusual_days()[Date.to_string(self.friday)],
            "and the calendar has to agree with it",
        )
        self.assertNotIn(self.friday, self._worked_dates())

    def test_flexible_resource_keeps_its_availability(self):
        """A resource with no calendar is available all week regardless.

        Its intervals carry a dummy attendance rather than a real line, so
        nothing about the calendar's typing may reach them. Upstream needs a
        guard in ``resource`` for the same reason.
        """
        self.fridays.work_entry_type_id = self.unpaid
        flexible = self.env["resource.resource"].create(
            {
                "name": "No calendar of their own",
                "calendar_id": False,
                "tz": "UTC",
                "company_id": self.env.company.id,
            }
        )
        intervals = self.calendar._work_intervals_batch(
            self.monday, self.sunday, resources=flexible
        )[flexible.id]
        self.assertEqual(len(intervals), 7)

    def test_a_plain_user_can_still_read_the_schedule(self):
        """`mrp`, `project` and `hr_calendar` reach this for ordinary users.

        ``work_entry_type_id`` is behind ``hr.group_hr_user``, so reading it
        unsudoed here would raise AccessError in modules that have nothing to
        do with payroll.
        """
        self.fridays.work_entry_type_id = self.unpaid
        joe = new_test_user(self.env, login="joe_no_hr", groups="base.group_user")
        self.assertFalse(joe.has_group("hr.group_hr_user"))
        self.assertNotIn(self.friday, self._worked_dates())
        calendar = self.calendar.with_user(joe)
        worked = {
            interval[0].date()
            for interval in calendar._work_intervals_batch(self.monday, self.sunday)[
                False
            ]
        }
        self.assertNotIn(self.friday, worked)
