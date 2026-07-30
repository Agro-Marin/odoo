"""Tests for current job skills filtering and internal resume lines."""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCurrentJobSkills(TransactionCase):
    """Validity filtering of a job's current skill requirements."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env["hr.job"].create({"name": "Skilled job"})
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "JS type"})
        cls.level = cls.env["hr.skill.level"].create(
            {
                "name": "JS level",
                "skill_type_id": cls.skill_type.id,
                "level_progress": 50,
            },
        )
        cls.skill_live, cls.skill_dead = cls.env["hr.skill"].create(
            [
                {"name": "JS live", "skill_type_id": cls.skill_type.id},
                {"name": "JS dead", "skill_type_id": cls.skill_type.id},
            ],
        )
        today = date.today()
        cls.job_skill_live, cls.job_skill_dead = cls.env["hr.job.skill"].create(
            [
                {
                    "job_id": cls.job.id,
                    "skill_id": cls.skill_live.id,
                    "skill_level_id": cls.level.id,
                    "skill_type_id": cls.skill_type.id,
                    "valid_from": today - relativedelta(months=2),
                    "valid_to": False,
                },
                {
                    "job_id": cls.job.id,
                    "skill_id": cls.skill_dead.id,
                    "skill_level_id": cls.level.id,
                    "skill_type_id": cls.skill_type.id,
                    "valid_from": today - relativedelta(months=2),
                    "valid_to": today - relativedelta(months=1),
                },
            ],
        )

    def test_current_job_skills_exclude_expired(self):
        """Only skills valid today appear in current_job_skill_ids."""
        self.assertEqual(self.job.current_job_skill_ids, self.job_skill_live)

    def test_current_job_skills_searchable(self):
        """The computed field is searchable with the 'in' operator."""
        jobs = self.env["hr.job"].search(
            [("current_job_skill_ids", "in", self.job_skill_live.ids)]
        )
        self.assertIn(self.job, jobs)

        jobs_dead = self.env["hr.job"].search(
            [("current_job_skill_ids", "in", self.job_skill_dead.ids)]
        )
        self.assertNotIn(self.job, jobs_dead)

    def test_current_job_skills_unsupported_operator(self):
        """Unsupported search operators must fail loudly, not silently."""
        with self.assertRaises(NotImplementedError):
            self.env["hr.job"]._search_current_job_skill_ids("=", True)


@tagged("post_install", "-at_install")
class TestInternalResumeLines(TransactionCase):
    """Version-derived resume lines exposed to the profile page."""

    def test_no_res_id_returns_empty(self):
        self.assertEqual(
            self.env["hr.employee"].get_internal_resume_lines(False, "hr.employee"),
            [],
        )

    def test_single_version_with_job_title_yields_one_line(self):
        employee = self.env["hr.employee"].create(
            {"name": "Resume employee", "job_title": "Chief Tester"},
        )
        lines = self.env["hr.employee"].get_internal_resume_lines(
            employee.id, "hr.employee"
        )

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["job_title"], "Chief Tester")
        self.assertFalse(lines[0]["date_end"])
