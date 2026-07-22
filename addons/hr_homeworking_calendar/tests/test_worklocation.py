"""Tests for the calendar work-location aggregation."""

from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWorkLocation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "HWC employee"})
        cls.location = cls.env["hr.work.location"].create(
            {
                "name": "HWC home",
                "location_type": "home",
                "address_id": cls.env.company.partner_id.id,
            }
        )

    def test_worklocation_base_structure(self):
        """Each employee entry carries identity plus a slot per weekday."""
        data = self.employee._get_worklocation(date(2026, 1, 5), date(2026, 1, 11))
        entry = data[self.employee.id]
        self.assertEqual(entry["employee_id"], self.employee.id)
        self.assertEqual(entry["employee_name"], "HWC employee")
        for day in ("monday_location_id", "sunday_location_id"):
            self.assertIn(day, entry)
            self.assertIn("location_type", entry[day])

    def test_worklocation_includes_period_exceptions(self):
        """A location exception inside the range surfaces under 'exceptions'."""
        self.env["hr.employee.location"].create(
            {
                "employee_id": self.employee.id,
                "work_location_id": self.location.id,
                "date": date(2026, 1, 7),
            }
        )
        data = self.employee._get_worklocation(date(2026, 1, 5), date(2026, 1, 11))
        entry = data[self.employee.id]
        self.assertIn("exceptions", entry)
        self.assertIn("2026-01-07", entry["exceptions"])
        self.assertEqual(
            entry["exceptions"]["2026-01-07"]["work_location_id"], self.location.id
        )

    def test_worklocation_no_exceptions_outside_range(self):
        """An exception outside the window is not included (boundary)."""
        self.env["hr.employee.location"].create(
            {
                "employee_id": self.employee.id,
                "work_location_id": self.location.id,
                "date": date(2026, 2, 20),
            }
        )
        data = self.employee._get_worklocation(date(2026, 1, 5), date(2026, 1, 11))
        self.assertNotIn("exceptions", data[self.employee.id])
