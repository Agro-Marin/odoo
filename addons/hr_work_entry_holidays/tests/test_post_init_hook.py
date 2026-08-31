from datetime import date

from odoo.tests.common import TransactionCase

from odoo.addons.hr_work_entry_holidays import _validate_existing_work_entry


class TestValidateExistingWorkEntry(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Post Init Subject",
                "contract_date_start": "2023-01-01",
                "date_version": "2023-01-01",
            }
        )
        cls.work_entry_type = cls.env["hr.work.entry.type"].create(
            {"name": "Post Init Attendance", "code": "POSTINIT_ATT"}
        )

    def _create(self, day, **vals):
        return self.env["hr.work.entry"].create(
            {
                "employee_id": self.employee.id,
                "work_entry_type_id": self.work_entry_type.id,
                "date": day,
                "duration": 8.0,
                **vals,
            }
        )

    def _break_it(self, entry):
        entry.with_context(hr_work_entry_no_check=True).write(
            {"work_entry_type_id": False}
        )
        return entry

    def test_hook_leaves_a_validated_entry_alone(self):
        validated = self._create(date(2024, 4, 1))
        validated.action_validate()
        self._break_it(validated)

        _validate_existing_work_entry(self.env)

        self.assertEqual(
            validated.state,
            "validated",
            "This hook runs `search([])._check_if_error()` over EVERY work entry "
            "in the database on install. _check_if_error narrows to entries that "
            "are neither validated nor cancelled, so the hook cannot flag a day "
            "payroll has already banked. Widen it again and installing this "
            "module silently demotes validated entries to draft, because "
            "_error_checking resets anything it finds in conflict.",
        )

    def test_hook_never_sees_a_cancelled_entry(self):
        cancelled = self._create(date(2024, 4, 2), state="cancelled")

        self.assertNotIn(
            cancelled,
            self.env["hr.work.entry"].search([]),
            "A cancelled entry is archived, and the hook's `search([])` runs with "
            "the default active_test, so archived rows never reach "
            "_check_if_error at all. That -- not the state filter inside "
            "_check_if_error -- is what keeps this hook away from them. If "
            "cancelled entries ever stop being archived, or this search gains "
            "active_test=False, the state filter becomes the only thing standing "
            "between an install and a table of resurrected work entries.",
        )

    def test_hook_still_flags_an_open_entry(self):
        entry = self._break_it(self._create(date(2024, 4, 3)))

        _validate_existing_work_entry(self.env)

        self.assertEqual(
            entry.state,
            "conflict",
            "The hook must still do its job for entries that are genuinely open: "
            "narrowing it to validated and cancelled must not turn it into a "
            "no-op for everything.",
        )
