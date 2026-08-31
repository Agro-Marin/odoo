from datetime import date

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestHrHolidaysControllers(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Controller Co"})
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.officer = cls.env["res.users"].create(
            {
                "name": "Controller Officer",
                "login": "controller_officer",
                "password": "controller_officer",
                "company_id": cls.company.id,
                "company_ids": [(6, 0, cls.company.ids)],
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("hr_holidays.group_hr_holidays_manager").id,
                        ],
                    )
                ],
            }
        )
        cls.env["hr.employee"].create(
            {
                "name": "Controller Officer",
                "user_id": cls.officer.id,
                "company_id": cls.company.id,
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Controller Emp", "company_id": cls.company.id}
        )
        cls.leave_type = cls.env["hr.leave.type"].create(
            {
                "name": "Controller Type",
                "company_id": cls.company.id,
                "requires_allocation": False,
                "request_unit": "day",
                "leave_validation_type": "hr",
            }
        )

    def _leave(self, day):
        return (
            self.env["hr.leave"]
            .with_user(self.officer)
            .create(
                {
                    "employee_id": self.employee.id,
                    "holiday_status_id": self.leave_type.id,
                    "request_date_from": day,
                    "request_date_to": day,
                }
            )
        )

    def _token(self, path, record):
        return (
            self.env["mixin.mail.thread"]
            .sudo()
            ._encode_link(path, {"res_id": record.id})
        )

    def test_approve_route_moves_the_leave(self):
        leave = self._leave(date(2027, 2, 1))
        self.authenticate("controller_officer", "controller_officer")
        self.url_open(
            f"/leave/approve?res_id={leave.id}"
            f"&token={self._token('/leave/approve', leave)}"
        )
        self.assertEqual(leave.state, "validate")

    def test_legacy_validate_route_is_the_same_action(self):
        leave = self._leave(date(2027, 2, 8))
        self.authenticate("controller_officer", "controller_officer")
        self.url_open(
            f"/leave/validate?res_id={leave.id}"
            f"&token={self._token('/leave/validate', leave)}"
        )
        self.assertEqual(
            leave.state,
            "validate",
            "/leave/validate is kept for links sent before the routes were unified "
            "and must stay equivalent to /leave/approve",
        )

    def test_refuse_route_moves_the_leave(self):
        leave = self._leave(date(2027, 2, 15))
        self.authenticate("controller_officer", "controller_officer")
        self.url_open(
            f"/leave/refuse?res_id={leave.id}"
            f"&token={self._token('/leave/refuse', leave)}"
        )
        self.assertEqual(leave.state, "refuse")

    def test_a_wrong_token_changes_nothing(self):
        leave = self._leave(date(2027, 3, 1))
        self.authenticate("controller_officer", "controller_officer")
        self.url_open(f"/leave/approve?res_id={leave.id}&token=not-a-real-token")
        self.assertEqual(
            leave.state,
            "confirm",
            "the token is the whole authorisation for these GET routes",
        )

    @mute_logger("odoo.addons.hr_holidays.controllers.main")
    def test_a_non_numeric_res_id_redirects_instead_of_raising(self):
        self.authenticate("controller_officer", "controller_officer")
        response = self.url_open("/leave/approve?res_id=not-an-int&token=whatever")
        self.assertEqual(
            response.status_code,
            200,
            "int(res_id) on unvalidated query input used to raise ValueError out "
            "of the route, which is a 500 rather than a redirect",
        )

    @mute_logger("odoo.addons.hr_holidays.controllers.main")
    def test_a_failing_action_redirects_to_the_fallback(self):
        leave = self._leave(date(2027, 3, 8))
        leave.action_approve()
        self.assertEqual(leave.state, "validate")
        self.authenticate("controller_officer", "controller_officer")
        response = self.url_open(
            f"/leave/approve?res_id={leave.id}"
            f"&token={self._token('/leave/approve', leave)}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            leave.state,
            "validate",
            "approving an already approved leave raises 'You can't do the same "
            "action twice'; the route must turn that into a redirect, and the "
            "handler must log the reason rather than discarding it",
        )

    def test_allocation_routes(self):
        allocation = (
            self.env["hr.leave.allocation"]
            .with_user(self.officer)
            .create(
                {
                    "name": "Controller alloc",
                    "employee_id": self.employee.id,
                    "holiday_status_id": self.leave_type.id,
                    "number_of_days": 1,
                }
            )
        )
        self.authenticate("controller_officer", "controller_officer")
        self.url_open(
            f"/allocation/validate?res_id={allocation.id}"
            f"&token={self._token('/allocation/validate', allocation)}"
        )
        self.assertEqual(allocation.state, "validate")
