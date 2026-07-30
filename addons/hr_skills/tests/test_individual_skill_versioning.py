"""Tests for the individual-skill versioning engine on employees."""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestIndividualSkillVersioning(TransactionCase):
    """Same-day edits replace; past skills version with an expiry date.

    The employee-side contract mirrors the defect tracked for applicants in
    t24152 (same-day edit leaving a duplicated versioned row): these tests
    pin the CORRECT behaviour so the applicant fix can be verified against
    the same expectations.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "ISV type"})
        cls.level_1, cls.level_2 = cls.env["hr.skill.level"].create(
            [
                {
                    "name": "ISV half",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 50,
                },
                {
                    "name": "ISV full",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 100,
                },
            ],
        )
        cls.skill_a, cls.skill_b = cls.env["hr.skill"].create(
            [
                {"name": "ISV skill A", "skill_type_id": cls.skill_type.id},
                {"name": "ISV skill B", "skill_type_id": cls.skill_type.id},
            ],
        )
        cls.employee = cls.env["hr.employee"].create({"name": "ISV employee"})

    def _skills_for(self, skill):
        return self.employee.employee_skill_ids.filtered(lambda s: s.skill_id == skill)

    def test_same_day_level_edit_replaces_record(self):
        """Editing a skill created today must replace it, never duplicate."""
        skill = self.env["hr.employee.skill"].create(
            {
                "employee_id": self.employee.id,
                "skill_id": self.skill_a.id,
                "skill_level_id": self.level_1.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": self.today,
                "valid_to": False,
            },
        )
        self.employee.write(
            {
                "current_employee_skill_ids": [
                    [1, skill.id, {"skill_level_id": self.level_2.id}]
                ],
            },
        )

        rows = self._skills_for(self.skill_a)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.skill_level_id, self.level_2)

    def test_past_skill_level_edit_versions_history(self):
        """Editing an old skill expires it yesterday and creates the new row."""
        skill = self.env["hr.employee.skill"].create(
            {
                "employee_id": self.employee.id,
                "skill_id": self.skill_b.id,
                "skill_level_id": self.level_1.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": self.today - relativedelta(months=2),
                "valid_to": False,
            },
        )
        self.employee.write(
            {
                "current_employee_skill_ids": [
                    [1, skill.id, {"skill_level_id": self.level_2.id}]
                ],
            },
        )

        rows = self._skills_for(self.skill_b).sorted("valid_from")
        self.assertEqual(len(rows), 2)
        old, new = rows
        self.assertEqual(old.skill_level_id, self.level_1)
        self.assertEqual(old.valid_to, self.today - relativedelta(days=1))
        self.assertEqual(new.skill_level_id, self.level_2)
        self.assertFalse(new.valid_to)
