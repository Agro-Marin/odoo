from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOvertimeLineScoping(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "Scoping A"})
        cls.company_b = cls.env["res.company"].create({"name": "Scoping B"})
        cls.officer = cls.env["res.users"].create(
            {
                "name": "Scoping Officer",
                "login": "scoping_officer",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id])],
                "group_ids": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(
                        cls.env.ref("hr_attendance.group_hr_attendance_officer").id
                    ),
                ],
            }
        )
        cls.managed = cls.env["hr.employee"].create(
            {
                "name": "Managed",
                "company_id": cls.company_a.id,
                "attendance_manager_id": cls.officer.id,
            }
        )
        cls.unmanaged = cls.env["hr.employee"].create(
            {"name": "Unmanaged", "company_id": cls.company_a.id}
        )
        cls.other_company = cls.env["hr.employee"].create(
            {"name": "Other Company", "company_id": cls.company_b.id}
        )
        cls.lines = {
            key: cls.env["hr.attendance.overtime.line"].create(
                {
                    "employee_id": employee.id,
                    "date": "2026-01-05",
                    "duration": 3.0,
                    "time_start": "2026-01-05 08:00:00",
                    "time_stop": "2026-01-05 11:00:00",
                }
            )
            for key, employee in (
                ("managed", cls.managed),
                ("unmanaged", cls.unmanaged),
                ("other_company", cls.other_company),
            )
        }

    def _as_officer(self):
        return self.env["hr.attendance.overtime.line"].with_user(self.officer)

    def test_officer_reads_only_managed_employees_lines(self):
        visible = self._as_officer().search(
            [("id", "in", [line.id for line in self.lines.values()])]
        )
        self.assertEqual(
            visible,
            self.lines["managed"].with_user(self.officer),
            "an officer must see the overtime lines of the employees they manage "
            "and no others -- the same scope their hr.attendance access has",
        )

    def test_officer_cannot_approve_an_unmanaged_employees_overtime(self):
        with self.assertRaises(AccessError):
            self.lines["unmanaged"].with_user(self.officer).action_approve()

    def test_officer_cannot_inflate_an_unmanaged_employees_paid_hours(self):
        with self.assertRaises(AccessError):
            self.lines["unmanaged"].with_user(self.officer).manual_duration = 99.0

    def test_officer_cannot_reach_another_companys_lines(self):
        with self.assertRaises(AccessError):
            self.lines["other_company"].with_user(self.officer).read(["duration"])

    def test_attendance_user_keeps_full_access(self):
        self.officer.group_ids = [
            Command.link(self.env.ref("hr_attendance.group_hr_attendance_user").id)
        ]
        visible = self._as_officer().search(
            [("id", "in", [line.id for line in self.lines.values()])]
        )
        self.assertIn(self.lines["unmanaged"].id, visible.ids)
        self.assertNotIn(
            self.lines["other_company"].id,
            visible.ids,
            "the multi-company rule is global and still applies",
        )
