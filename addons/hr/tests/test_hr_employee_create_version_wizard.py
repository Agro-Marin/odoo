from datetime import date

from odoo.addons.hr.tests.common import TestHrCommon


class TestHrEmployeeCreateVersionWizard(TestHrCommon):
    """Creating one new version for a whole selection of employees at once."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employees = cls.env["hr.employee"].create(
            [{"name": "Ana"}, {"name": "Beto"}, {"name": "Carla"}]
        )
        cls.new_date = date(2027, 1, 1)

    def _wizard(self, employees, **values):
        return (
            self.env["hr.employee.create.version.wizard"]
            .with_context(active_ids=employees.ids)
            .create({"date_version": self.new_date, **values})
        )

    def test_creates_one_version_per_selected_employee(self):
        versions_before = {
            employee: len(employee.version_ids) for employee in self.employees
        }
        wizard = self._wizard(self.employees)
        self.assertEqual(wizard.employee_count, 3)

        wizard.action_create_versions()

        for employee in self.employees:
            self.assertEqual(
                len(employee.version_ids), versions_before[employee] + 1, employee.name
            )
            self.assertIn(self.new_date, employee.version_ids.mapped("date_version"))

    def test_leaves_unselected_employees_alone(self):
        untouched = self.env["hr.employee"].create({"name": "Dora"})
        versions_before = len(untouched.version_ids)

        self._wizard(self.employees).action_create_versions()

        self.assertEqual(len(untouched.version_ids), versions_before)
        self.assertNotIn(self.new_date, untouched.version_ids.mapped("date_version"))

    def test_an_empty_selection_creates_nothing(self):
        wizard = self._wizard(self.env["hr.employee"])
        self.assertEqual(wizard.employee_count, 0)
        self.assertEqual(
            wizard.action_create_versions(), {"type": "ir.actions.act_window_close"}
        )
