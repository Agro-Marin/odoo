from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestLeaveApproverGrant(TransactionCase):
    def test_the_approver_group_follows_the_leave_manager_with_its_cause(self):
        officer = new_test_user(
            self.env,
            login="leave_grant_officer",
            groups="base.group_user,hr.group_hr_user,hr_holidays.group_hr_holidays_user",
        )
        manager = new_test_user(
            self.env, login="leave_grant_manager", groups="base.group_user"
        )
        approver = self.env.ref("hr_holidays.group_hr_holidays_responsible")
        employee = (
            self.env["hr.employee"]
            .with_user(officer)
            .create({"name": "Leave grant probe", "leave_manager_id": manager.id})
        )
        grant = self.env["res.users.grant"].search(
            [("user_id", "=", manager.id), ("group_id", "=", approver.id)]
        )
        self.assertEqual(grant.cause, "automation")
        self.assertEqual(grant.cause_model, "hr.employee")
        self.assertEqual(grant.granted_by_id, officer)
        self.assertTrue(manager.has_group("hr_holidays.group_hr_holidays_responsible"))
        self.assertTrue(
            self.env["ir.access.log"].search_count(
                [
                    ("event", "=", "privilege_used"),
                    ("model_name", "=", "res.users.grant"),
                    ("actor_id", "=", officer.id),
                ]
            )
        )
        employee.with_user(officer).leave_manager_id = False
        self.assertEqual(grant.state, "revoked")
        self.assertFalse(manager.has_group("hr_holidays.group_hr_holidays_responsible"))
