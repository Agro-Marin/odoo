from odoo.tests import Form, TransactionCase, tagged


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
