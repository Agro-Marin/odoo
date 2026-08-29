from datetime import date

from odoo.tests import tagged

from odoo.addons.hr.tests.common import TestHrCommon


@tagged("post_install", "-at_install")
class TestHrEmployeeRights(TestHrCommon):
    """The HR Officer owns onboarding, so the contract dates are theirs to see.

    Field groups are enforced on read, so every probe below goes through SQL
    (a `search` domain) or through an invalidated cache -- a value already read
    as superuser would come back from the cache without any access check.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = cls.res_users_hr_officer
        cls.hired = cls.env["hr.employee"].create(
            {
                "name": "Hired",
                "date_version": "2020-01-01",
                "contract_date_start": "2020-01-01",
            }
        )

    def test_the_officer_is_not_a_manager(self):
        """Guard the fixture: an HR Manager would prove nothing here."""
        self.assertTrue(self.officer.has_group("hr.group_hr_user"))
        self.assertFalse(self.officer.has_group("hr.group_hr_manager"))

    def test_an_officer_can_search_employees_by_contract_start_date(self):
        found = (
            self.env["hr.employee"]
            .with_user(self.officer)
            .search(
                [("contract_date_start", "<", "2022-01-01"), ("id", "=", self.hired.id)]
            )
        )
        self.assertEqual(found, self.hired)

    def test_an_officer_can_read_the_contract_dates(self):
        self.env.invalidate_all()
        employee = self.hired.with_user(self.officer)
        self.assertEqual(employee.contract_date_start, date(2020, 1, 1))
        self.assertTrue(employee.is_in_contract)
        self.assertTrue(employee.is_current)

    def test_an_officer_can_set_a_contract_end_date(self):
        self.hired.with_user(self.officer).contract_date_end = "2026-12-31"
        self.assertEqual(self.hired.contract_date_end, date(2026, 12, 31))

    def test_the_wage_stays_out_of_reach(self):
        """The widening is about the dates only, not about the payroll fields."""
        self.assertEqual(
            self.env["hr.version"]._fields["wage"].groups, "hr.group_hr_manager"
        )
