"""A project's start and expiration dates travel together."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestProjectDatePair(TestProjectCommon):
    def test_create_rejects_a_half_set_pair(self) -> None:
        """``write`` refused it and ``create`` did not, so a one-sided project
        was creatable but then unrepairable field-by-field."""
        with self.assertRaises(UserError):
            self.env["project.project"].create(
                {"name": "Half", "date_start": fields.Date.today()}
            )

    def test_both_dates_together_is_accepted(self) -> None:
        today = fields.Date.today()
        project = self.env["project.project"].create(
            {"name": "Whole", "date_start": today, "date": today}
        )
        self.assertEqual(project.date_start, today)

    def test_neither_date_is_accepted(self) -> None:
        project = self.env["project.project"].create({"name": "Undated"})
        self.assertFalse(project.date_start)
        self.assertFalse(project.date)


@tagged("post_install", "-at_install")
class TestUnusualDays(TestProjectCommon):
    """The non-working days the date pickers grey out."""

    def test_get_unusual_days_accepts_one_date(self) -> None:
        """The signature advertised date_to as optional but crashed without it."""
        self.env["project.task"].get_unusual_days("2026-07-01")  # must not raise
