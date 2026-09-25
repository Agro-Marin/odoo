from datetime import date, timedelta

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.authority_keys import strip_authority_keys

# row, persona, model, validation type, whose record, state, verb: a cell the
# row alone grants, so switching the row off takes exactly that move away
ROW_CELLS = [
    line.split()
    for line in """
    access_hr_leave_approve_officer officer leave both employee refuse approve
    access_hr_leave_approve_manager manager leave both employee confirm approve
    access_hr_leave_validate_officer officer leave hr employee confirm validate
    access_hr_leave_validate_manager manager leave manager employee confirm validate
    access_hr_leave_refuse_officer officer leave hr employee confirm refuse
    access_hr_leave_refuse_manager manager leave manager employee confirm refuse
    access_hr_leave_refuse_manager_first_step manager leave both employee validate1 refuse
    access_hr_leave_reset_officer officer leave hr employee validate reset
    access_hr_leave_cancel employee leave hr employee validate cancel
    access_hr_leave_allocation_approve_officer officer allocation both employee refuse approve
    access_hr_leave_allocation_approve_administrator admin allocation both admin confirm approve
    access_hr_leave_allocation_approve_manager manager allocation both employee confirm approve
    access_hr_leave_allocation_validate_officer officer allocation hr employee confirm validate
    access_hr_leave_allocation_validate_administrator admin allocation hr admin confirm validate
    access_hr_leave_allocation_validate_manager manager allocation manager employee confirm validate
    access_hr_leave_allocation_validate_unvalidated employee allocation no_validation employee confirm validate
    access_hr_leave_allocation_refuse_officer officer allocation hr employee confirm refuse
    access_hr_leave_allocation_refuse_administrator admin allocation hr admin confirm refuse
    access_hr_leave_allocation_refuse_manager manager allocation manager employee confirm refuse
    access_hr_leave_allocation_refuse_manager_first_step manager allocation both employee validate1 refuse
    access_hr_leave_allocation_reset_officer officer allocation hr employee validate reset
    access_hr_leave_allocation_reset_administrator admin allocation hr admin validate reset
""".strip().splitlines()
]


@tagged("post_install", "-at_install")
class TestLeaveVerbs(TransactionCase):
    """Approving, validating, refusing and resetting a leave or an allocation are
    verbs of hr.leave and hr.leave.allocation, granted by security/ir_access.xml
    exactly as _get_next_states_by_state granted them before."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        groups = {
            "employee": "base.group_user",
            "manager": "base.group_user",
            "officer": "base.group_user,hr_holidays.group_hr_holidays_user",
            "admin": "base.group_user,hr_holidays.group_hr_holidays_manager",
        }
        cls.users = {
            key: new_test_user(cls.env, login=f"verb_{key}", groups=spec)
            for key, spec in groups.items()
        }
        cls.employees = {
            key: cls.env["hr.employee"].create(
                {"name": f"Verb {key}", "user_id": user.id}
            )
            for key, user in cls.users.items()
        }
        cls.employees["employee"].leave_manager_id = cls.users["manager"]
        cls.leave_types = {
            vt: cls.env["hr.leave.type"].create(
                {
                    "name": f"Verb leave {vt}",
                    "leave_validation_type": vt,
                    "requires_allocation": False,
                }
            )
            for vt in ("hr", "manager", "both")
        }
        cls.allocation_types = {
            vt: cls.env["hr.leave.type"].create(
                {
                    "name": f"Verb allocation {vt}",
                    "allocation_validation_type": vt,
                    "requires_allocation": True,
                }
            )
            for vt in ("no_validation", "hr", "manager", "both")
        }
        cls.next_day = date(2031, 3, 3)

    def _record(self, kind, validation_type, whose, state):
        employee = self.employees[whose]
        if kind == "leave":
            day = self.next_day
            while day.weekday() >= 5:
                day += timedelta(days=1)
            self.next_day = day + timedelta(days=1)
            record = (
                self.env["hr.leave"]
                .with_context(leave_fast_create=True, leave_skip_state_check=True)
                .create(
                    {
                        "employee_id": employee.id,
                        "holiday_status_id": self.leave_types[validation_type].id,
                        "request_date_from": day,
                        "request_date_to": day,
                    }
                )
            )
        else:
            record = self.env["hr.leave.allocation"].create(
                {
                    "employee_id": employee.id,
                    "holiday_status_id": self.allocation_types[validation_type].id,
                    "number_of_days": 1,
                    "date_from": date(2031, 1, 1),
                }
            )
        if record.state != state:
            record.sudo().with_context(leave_fast_create=True).write({"state": state})
        return record

    def test_each_row_grants_its_move_and_only_it(self):
        for xmlid, persona, kind, validation_type, whose, state, verb in ROW_CELLS:
            with self.subTest(row=xmlid):
                record = self._record(kind, validation_type, whose, state)
                mine = record.with_user(self.users[persona])
                self.assertTrue(mine.has_access(verb))
                row = self.env.ref(f"hr_holidays.{xmlid}")
                row.active = False
                self.assertFalse(mine.has_access(verb), "no other row grants this move")
                row.active = True

    def test_the_move_is_the_verb_whoever_writes_it(self):
        leave = self._record("leave", "hr", "employee", "confirm")
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            # a time-off approver does not validate what an officer validates,
            # even by writing the state
            leave.with_user(self.users["manager"]).with_context(
                leave_fast_create=True
            ).write({"state": "validate"})
        with (
            mute_logger("odoo.addons.base.models.ir_access"),
            self.assertRaises(AccessError),
        ):
            # a context a client can send skips the leave's own check, and no
            # longer the verb
            leave.with_user(self.users["employee"]).with_context(
                leave_fast_create=True
            ).write({"state": "validate"})
        self.assertEqual(leave.state, "confirm")
        leave.with_user(self.users["officer"]).action_approve()
        self.assertEqual(leave.state, "validate")

    def test_a_client_cannot_send_the_fast_create_key(self):
        self.assertEqual(
            strip_authority_keys({"leave_fast_create": True, "lang": "en_US"}),
            {"lang": "en_US"},
        )

    def test_a_record_created_in_a_decided_state_is_not_the_move(self):
        leave = (
            self.env["hr.leave"]
            .with_user(self.users["manager"])
            .with_context(leave_fast_create=True, leave_skip_state_check=True)
            .create(
                {
                    "employee_id": self.employees["employee"].id,
                    "holiday_status_id": self.leave_types["manager"].id,
                    "request_date_from": date(2031, 5, 5),
                    "request_date_to": date(2031, 5, 5),
                    "state": "refuse",
                }
            )
        )
        self.assertEqual(leave.state, "refuse")
        self.assertFalse(
            leave.with_user(self.users["manager"]).has_access("refuse"),
            "refusing it again would be the move, which starts from confirm",
        )
