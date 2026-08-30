import ast

from odoo.tests import TransactionCase


class TestEmployeeMassMail(TransactionCase):
    """HR needs to write to a selection of employees without opening each one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employees = cls.env["hr.employee"].create(
            [
                {"name": "Ana", "work_email": "ana@example.com"},
                {"name": "Beto", "work_email": "beto@example.com"},
            ]
        )

    def _employee_bindings(self):
        bindings = self.env["ir.actions.actions"].get_bindings("hr.employee")
        return bindings.get("action", [])

    def test_actions_menu_offers_a_mass_mail_composer(self):
        offered = {action["name"] for action in self._employee_bindings()}

        self.assertIn("Send Email", offered)

    def test_the_composer_is_bound_to_the_list_and_the_kanban(self):
        composer_binding = next(
            action
            for action in self._employee_bindings()
            if action["name"] == "Send Email"
        )

        self.assertEqual(composer_binding["binding_view_types"], "list,kanban")

    def test_the_composer_opens_in_mass_mail_mode_over_the_selection(self):
        action = self.env.ref("hr.action_employee_mass_mail")

        composer = (
            self.env["mail.compose.message"]
            .with_context(
                **ast.literal_eval(action.context),
                active_model="hr.employee",
                active_ids=self.employees.ids,
            )
            .create({"subject": "Aviso", "body": "<p>Aviso</p>"})
        )

        self.assertEqual(composer.composition_mode, "mass_mail")
        self.assertEqual(composer.model, "hr.employee")
        self.assertEqual(composer._evaluate_res_ids(), self.employees.ids)
