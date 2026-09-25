from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHrAccessBind(TransactionCase):
    # an employee anchor compares with every employee record of the principal,
    # as `employee_id.user_id = user.id` does; a unit anchor with the
    # departments its active employees work in

    def test_employees_and_units(self):
        user = self.env["res.users"].create(
            {
                "login": "binder",
                "name": "Binder",
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
            }
        )
        sales = self.env["hr.department"].create({"name": "Sales"})
        other = self.env["res.company"].create({"name": "Other"})
        working = self.env["hr.employee"].create(
            {"name": "Binder", "user_id": user.id, "department_id": sales.id}
        )
        gone = self.env["hr.employee"].create(
            {
                "name": "Binder elsewhere",
                "user_id": user.id,
                "company_id": other.id,
                "department_id": self.env["hr.department"]
                .create({"name": "Gone", "company_id": other.id})
                .id,
            }
        )
        gone.action_archive()
        access = self.env["ir.access"].with_user(user)
        self.assertEqual(access._access_bind_employees(), sorted((working + gone).ids))
        self.assertEqual(
            access._access_bind_employees(),
            self.env["hr.employee"]
            .with_context(active_test=False)
            .search([("user_id", "=", user.id)], order="id")
            .ids,
        )
        self.assertEqual(access._access_bind_units(), sales.ids)
