from datetime import date

from odoo.tests import tagged

from odoo.addons.hr.tests.common import TestHrCommon


@tagged("post_install", "-at_install")
class TestFirstContractDate(TestHrCommon):
    """Seniority is the date the employee started, not the date of the contract
    they happen to be on now.

    A renewal opens a new version with a new `contract_date_start`, so every
    place that reads the current version answers with the renewal date. What an
    HR manager wants on a kanban card is when this person joined.
    """

    def _employee(self, contract_date_start="2026-01-01", **values):
        return self.env["hr.employee"].create(
            {
                "name": "Seniority",
                "date_version": contract_date_start,
                "contract_date_start": contract_date_start,
                **values,
            }
        )

    def test_a_single_contract_is_the_first_contract_date(self):
        employee = self._employee()
        self.assertEqual(employee.first_contract_date, date(2026, 1, 1))

    def test_a_later_version_does_not_move_the_date(self):
        employee = self._employee()
        employee.create_version({"date_version": "2026-02-01"})
        self.assertEqual(employee.first_contract_date, date(2026, 1, 1))

    def test_a_renewed_contract_keeps_the_original_start(self):
        employee = self._employee(contract_date_end="2026-01-31")
        employee.create_version(
            {
                "date_version": "2026-02-01",
                "contract_date_start": "2026-02-01",
                "contract_date_end": "2026-02-28",
            }
        )
        employee.create_version(
            {"date_version": "2026-03-01", "contract_date_start": "2026-03-01"}
        )

        self.assertEqual(employee.first_contract_date, date(2026, 1, 1))
        self.assertEqual(
            employee.contract_date_start,
            date(2026, 3, 1),
            "the current version still answers with the renewal date",
        )

    def test_deleting_the_first_version_moves_the_date(self):
        employee = self._employee(contract_date_end="2026-01-31")
        first_version = employee.version_id
        employee.create_version(
            {"date_version": "2026-02-01", "contract_date_start": "2026-02-01"}
        )
        self.assertEqual(employee.first_contract_date, date(2026, 1, 1))

        first_version.unlink()

        self.assertEqual(employee.first_contract_date, date(2026, 2, 1))

    def test_a_rehire_after_a_break_starts_a_new_seniority(self):
        """Our own rule, not upstream's: a gap of more than four days between
        two contracts is a new occupation, so the earlier stint does not count.
        """
        employee = self._employee(contract_date_end="2026-01-31")
        employee.create_version(
            {"date_version": "2026-06-01", "contract_date_start": "2026-06-01"}
        )

        self.assertEqual(employee.first_contract_date, date(2026, 6, 1))
