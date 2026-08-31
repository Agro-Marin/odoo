from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class TestWorkEntryAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = cls.env["res.users"].create(
            {
                "name": "Work Entry Officer",
                "login": "work_entry_officer",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("hr.group_hr_user").id),
                ],
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Access Subject",
                "contract_date_start": "2023-01-01",
                "date_version": "2023-01-01",
            }
        )
        cls.work_entry_type = cls.env["hr.work.entry.type"].create(
            {"name": "Access Attendance", "code": "ACCESS_ATT"}
        )

    def _create_as_officer(self, day, **vals):
        return (
            self.env["hr.work.entry"]
            .with_user(self.officer)
            .create(
                {
                    "employee_id": self.employee.id,
                    "work_entry_type_id": self.work_entry_type.id,
                    "date": day,
                    "duration": 4.0,
                    **vals,
                }
            )
        )

    def test_officer_can_delete_a_draft_work_entry(self):
        entry = self._create_as_officer(date(2024, 5, 1))
        entry.unlink()
        self.assertFalse(
            entry.exists(),
            "An HR officer must be able to delete a work entry that is not "
            "validated. The work entry calendar offers exactly this: "
            "onMultiDelete unlinks the selected records, and multiReplaceRecords "
            "unlinks the entries it replaces. Without the unlink right those two "
            "core workflows raise AccessError for the group that owns the screen, "
            "and _unlink_except_validated_work_entries -- which exists to allow "
            "deleting everything except validated entries -- guards nothing.",
        )

    def test_officer_cannot_delete_a_validated_work_entry(self):
        entry = self._create_as_officer(date(2024, 5, 2))
        entry.action_validate()
        self.assertEqual(entry.state, "validated")
        with self.assertRaises(UserError):
            entry.unlink()

    def test_regenerating_work_entries_stays_manager_only(self):
        with self.assertRaises(
            AccessError,
            msg="Regenerating work entries is restricted to hr.group_hr_manager, "
            "and the calendar's two Reset controls are hidden from anyone else on "
            "the strength of that. If this ACL is ever widened, the UI gate in "
            "useWorkEntry becomes wrong in the other direction -- it will hide a "
            "button the user is now entitled to press. Widen both or neither. "
            "This assertion exists because the gate itself is enforced only by "
            "HOOT tests, and no workflow in .github/workflows runs JavaScript.",
        ):
            self.env["hr.work.entry.regeneration.wizard"].with_user(
                self.officer
            ).create(
                {
                    "date_from": date(2024, 5, 1),
                    "date_to": date(2024, 5, 31),
                    "employee_ids": [(6, 0, [self.employee.id])],
                }
            )

    def test_officer_can_replace_work_entries_on_a_day(self):
        replaced = self._create_as_officer(date(2024, 5, 3))
        other_type = self.env["hr.work.entry.type"].create(
            {"name": "Access Overtime", "code": "ACCESS_OVT"}
        )
        entries = self.env["hr.work.entry"].with_user(self.officer)
        try:
            created = entries.create(
                {
                    "employee_id": self.employee.id,
                    "work_entry_type_id": other_type.id,
                    "date": date(2024, 5, 3),
                    "duration": 4.0,
                }
            )
            replaced.unlink()
        except AccessError as error:
            self.fail(
                "The calendar's multi-replace is create-then-unlink as one user "
                "action, so an HR officer needs both rights: %s" % error
            )
        self.assertTrue(created.exists())
        self.assertFalse(replaced.exists())
