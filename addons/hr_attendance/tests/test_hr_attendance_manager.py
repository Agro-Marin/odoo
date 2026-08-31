from odoo.exceptions import AccessError
from odoo.tests import new_test_user
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceManager(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.luisa = new_test_user(
            cls.env, login="luisa", groups="hr_attendance.group_hr_attendance_manager"
        )

        cls.marc = new_test_user(cls.env, login="marc", groups="base.group_user")
        cls.marc_employee = cls.env["hr.employee"].create(
            {
                "name": "Marc Employee",
                "user_id": cls.marc.id,
            }
        )
        cls.marc_employee.attendance_manager_id = cls.marc

        cls.abigail_employee, cls.ryan_employee = cls.env["hr.employee"].create(
            [
                {
                    "name": "Abigail Employee",
                    "attendance_manager_id": cls.marc.id,
                },
                {
                    "name": "Ryan Employee",
                    "attendance_manager_id": cls.luisa.id,
                },
            ]
        )

        cls.attendance = cls.env["hr.attendance"].create(
            {
                "employee_id": cls.marc_employee.id,
                "check_in": "2025-09-09 08:00:00",
                "check_out": "2025-09-09 12:00:00",
            }
        )

    def test_attendance_officer_rights(self):
        attendance_as_marc = self.attendance.with_user(self.marc)

        attendance_as_marc.write({"employee_id": self.abigail_employee.id})
        self.assertEqual(self.attendance.employee_id, self.abigail_employee)

        with self.assertRaises(AccessError):
            attendance_as_marc.write({"employee_id": self.ryan_employee.id})

    def test_attendance_manager_rights(self):
        attendance_as_luisa = self.attendance.with_user(self.luisa)

        attendance_as_luisa.write({"employee_id": self.abigail_employee.id})
        self.assertEqual(self.attendance.employee_id, self.abigail_employee)

        attendance_as_luisa.write({"employee_id": self.ryan_employee.id})
        self.assertEqual(self.attendance.employee_id, self.ryan_employee)
