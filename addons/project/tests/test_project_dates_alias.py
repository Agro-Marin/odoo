from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestProjectDateAlias(TestProjectCommon):
    START = "2028-01-01"
    END = "2028-12-31"

    def _dated(self, **extra):
        return self.env["project.project"].create(
            {
                "name": "Dated",
                "date_start": fields.Date.to_date(self.START),
                "date_end": fields.Date.to_date(self.END),
                **extra,
            }
        )

    def test_date_end_is_the_stored_field(self):
        Project = self.env["project.project"]
        self.assertTrue(Project._fields["date_end"].store)
        self.assertFalse(Project._fields["date_end"].related)
        self.assertEqual(Project._fields["date"].related, "date_end")

    def test_the_alias_reads_the_stored_value(self):
        project = self._dated()
        self.assertEqual(project.date, fields.Date.to_date(self.END))

    def test_writing_the_alias_moves_the_stored_value(self):
        project = self._dated()
        project.date = fields.Date.to_date("2029-06-30")
        self.assertEqual(project.date_end, fields.Date.to_date("2029-06-30"))

    def test_writing_the_stored_value_shows_through_the_alias(self):
        project = self._dated()
        project.write({"date_end": fields.Date.to_date("2029-07-31")})
        self.assertEqual(project.date, fields.Date.to_date("2029-07-31"))

    def test_the_alias_is_searchable(self):
        project = self._dated()
        self.assertIn(
            project,
            self.env["project.project"].search(
                [("date", "=", fields.Date.to_date(self.END))]
            ),
        )

    def test_create_accepts_either_spelling(self):
        by_alias = self.env["project.project"].create(
            {
                "name": "ByAlias",
                "date_start": fields.Date.to_date(self.START),
                "date": fields.Date.to_date(self.END),
            }
        )
        self.assertEqual(by_alias.date_end, fields.Date.to_date(self.END))

    def test_the_pair_check_sees_either_spelling(self):
        for field in ("date_end", "date"):
            with self.subTest(field=field), self.assertRaises(UserError):
                self.env["project.project"].create(
                    {"name": "Half", field: fields.Date.to_date(self.END)}
                )
        with self.assertRaises(UserError):
            self.env["project.project"].create(
                {"name": "Half", "date_start": fields.Date.to_date(self.START)}
            )

    def test_a_project_with_neither_date_is_allowed(self):
        self.assertTrue(self.env["project.project"].create({"name": "Undated"}))

    def test_writing_one_date_on_a_dated_project_keeps_the_pair(self):
        for field in ("date_end", "date"):
            with self.subTest(field=field):
                project = self._dated()
                project.write({field: fields.Date.to_date("2029-03-31")})
                self.assertEqual(
                    project.date_end, fields.Date.to_date("2029-03-31")
                )
