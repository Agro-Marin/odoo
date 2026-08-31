from unittest.mock import patch

from odoo.http import Request
from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install", "hr_attendance_kiosk")
class TestHrAttendanceKiosk(HttpCase):
    """Tests for kiosk"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_A = cls.env["res.company"].create({"name": "company_A"})
        cls.company_B = cls.env["res.company"].create({"name": "company_B"})

        cls.department_A = cls.env["hr.department"].create(
            {"name": "department_A", "company_id": cls.company_B.id}
        )

        cls.employee_A = cls.env["hr.employee"].create(
            {
                "name": "employee_A",
                "company_id": cls.company_B.id,
                "department_id": cls.department_A.id,
            }
        )
        cls.employee_B = cls.env["hr.employee"].create(
            {
                "name": "employee_B",
                "company_id": cls.company_A.id,
                "department_id": cls.department_A.id,
            }
        )

    def test_employee_count_kiosk(self):
        # the mock need to return a None value which can be converted into a Reponse object
        with patch.object(Request, "render", return_value=None) as render:
            self.url_open(self.company_B.attendance_kiosk_url)

        render.assert_called_once()
        _template, kiosk_info = render.call_args[0]
        kiosk_info = kiosk_info["kiosk_backend_info"]
        self.assertEqual(kiosk_info["company_name"], "company_B")
        self.assertEqual(kiosk_info["departments"][0]["count"], 1)

    def test_print_badge_from_kiosk_onboarding(self):
        """The kiosk can print the badge it just assigned, for its own company.

        The onboarding dialog runs in the public kiosk, so the company's kiosk
        token is the only thing identifying the caller -- and it must not open
        the badge of an employee of another company.
        """
        self.employee_A.barcode = "0000000001"
        self.employee_B.barcode = "0000000002"
        token = self.company_B.sudo().attendance_kiosk_key

        # employee_A belongs to company_B, whose token this is.
        response = self.url_open(
            f"/hr_attendance/print_badge?employee_id={self.employee_A.id}&token={token}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content)
        self.assertIn("employee_A", response.headers["Content-Disposition"])

        # employee_B belongs to company_A: company_B's token must not reach it.
        response = self.url_open(
            f"/hr_attendance/print_badge?employee_id={self.employee_B.id}&token={token}"
        )
        self.assertEqual(response.status_code, 404)

        # A badge that was never assigned has nothing to print.
        self.employee_A.barcode = False
        response = self.url_open(
            f"/hr_attendance/print_badge?employee_id={self.employee_A.id}&token={token}"
        )
        self.assertEqual(response.status_code, 404)
