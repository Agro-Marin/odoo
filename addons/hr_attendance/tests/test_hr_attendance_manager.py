from odoo.exceptions import AccessError
from odoo.tests import Form, new_test_user
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceManager(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create an attendance manager
        cls.luisa = new_test_user(
            cls.env, login="luisa", groups="hr_attendance.group_hr_attendance_manager"
        )

        # Create a normal user
        cls.marc = new_test_user(cls.env, login="marc", groups="base.group_user")
        cls.marc_employee = cls.env["hr.employee"].create(
            {
                "name": "Marc Employee",
                "user_id": cls.marc.id,
            }
        )
        cls.marc_employee.attendance_manager_id = cls.marc

        # Create another employee
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

        # Create an attendance for Marc Demo's employee
        cls.attendance = cls.env["hr.attendance"].create(
            {
                "employee_id": cls.marc_employee.id,
                "check_in": "2025-09-09 08:00:00",
                "check_out": "2025-09-09 12:00:00",
            }
        )

    def test_attendance_officer_rights(self):
        """Marc Demo should NOT be able to change the employee on his attendance
        if he is not assigned as attendance manager of that employee.
        """
        attendance_as_marc = self.attendance.with_user(self.marc)

        # Marc can change the employee to Abigail
        attendance_as_marc.write({"employee_id": self.abigail_employee.id})
        self.assertEqual(self.attendance.employee_id, self.abigail_employee)

        # Marc cannot change the employee to Ryan
        with self.assertRaises(AccessError):
            attendance_as_marc.write({"employee_id": self.ryan_employee.id})

    def test_attendance_manager_rights(self):
        """Luisa should be able to change the employee on attendance without the need
        of being set as attendance_manager since she has the attendance_manager group.
        """
        attendance_as_luisa = self.attendance.with_user(self.luisa)

        attendance_as_luisa.write({"employee_id": self.abigail_employee.id})
        self.assertEqual(self.attendance.employee_id, self.abigail_employee)

        attendance_as_luisa.write({"employee_id": self.ryan_employee.id})
        self.assertEqual(self.attendance.employee_id, self.ryan_employee)

    def test_approver_follows_the_new_manager(self):
        """Reassigning an employee's manager should move the attendance approver.

        Only when the approver was the outgoing manager: an approver somebody
        picked by hand is a deliberate choice and must survive the reassignment.
        """
        old_user = new_test_user(self.env, login="old_manager")
        new_user = new_test_user(self.env, login="new_manager")
        old_manager, new_manager = self.env["hr.employee"].create(
            [
                {"name": "Old Manager", "user_id": old_user.id},
                {"name": "New Manager", "user_id": new_user.id},
            ]
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Reassigned Employee",
                "parent_id": old_manager.id,
                "attendance_manager_id": old_user.id,
            }
        )

        with Form(employee) as employee_form:
            employee_form.parent_id = new_manager
        self.assertEqual(
            employee.attendance_manager_id,
            new_user,
            "the approver was the old manager, so it should follow to the new one",
        )

        # An approver set by hand is a deliberate choice and is left alone.
        third_party = new_test_user(self.env, login="third_party")
        employee.attendance_manager_id = third_party
        with Form(employee) as employee_form:
            employee_form.parent_id = old_manager
        self.assertEqual(
            employee.attendance_manager_id,
            third_party,
            "a hand-picked approver should not be overwritten by a manager change",
        )
