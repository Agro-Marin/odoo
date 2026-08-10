import datetime

from dateutil.rrule import MONTHLY

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase


class DateRangeGeneratorTest(TransactionCase):
    def setUp(self):
        super().setUp()
        self.generator = self.env["date.range.generator"]
        self.type = self.env["date.range.type"].create(
            {"name": "Fiscal year", "company_id": False, "allow_overlap": False}
        )

        self.company = self.env["res.company"].create({"name": "Test company"})
        self.company_2 = self.env["res.company"].create(
            {"name": "Test company 2", "parent_id": self.company.id}
        )
        self.type_b = self.env["date.range.type"].create(
            {
                "name": "Fiscal year B",
                "company_id": self.company.id,
                "allow_overlap": False,
            }
        )

    def test_generate(self):
        generator = self.generator.create(
            {
                "date_start": "1943-01-01",
                "name_prefix": "1943-",
                "type_id": self.type.id,
                "duration_count": 3,
                "unit_of_time": str(MONTHLY),
                "count": 4,
            }
        )
        generator.action_apply()
        ranges = self.env["date.range"].search([("type_id", "=", self.type.id)])
        self.assertEqual(len(ranges), 4)
        range4 = ranges[3]
        self.assertEqual(range4.date_start, datetime.date(1943, 10, 1))
        self.assertEqual(range4.date_end, datetime.date(1943, 12, 31))
        self.assertEqual(range4.type_id, self.type)

    def test_generator_multicompany_1(self):
        with self.assertRaises(ValidationError):
            self.generator.create(
                {
                    "date_start": "1943-01-01",
                    "name_prefix": "1943-",
                    "type_id": self.type_b.id,
                    "duration_count": 3,
                    "unit_of_time": str(MONTHLY),
                    "count": 4,
                    "company_id": self.company_2.id,
                }
            )

    def test_create_from_python_with_type_defaults(self):
        """create() works with only a type: the wizard fills its own defaults.

        The generation parameters used to carry required=True on top of a
        compute the ORM does not run before the INSERT, so this raised a raw
        NotNullViolation from psycopg.
        """
        dr_type = self.env["date.range.type"].create(
            {
                "name": "Configured",
                "allow_overlap": True,
                "name_prefix": "Q",
                "duration_count": 3,
                "unit_of_time": str(MONTHLY),
            }
        )
        wizard = self.generator.create({"type_id": dr_type.id, "count": 2})
        self.env.flush_all()
        self.assertEqual(wizard.duration_count, 3)
        self.assertEqual(wizard.unit_of_time, str(MONTHLY))
        self.assertEqual(wizard.name_prefix, "Q")
        self.assertTrue(wizard.date_start)
        wizard.action_apply()
        self.assertEqual(
            self.env["date.range"].search_count([("type_id", "=", dr_type.id)]), 2
        )

    def test_create_many_keeps_each_configuration(self):
        """The computes handle a multi-record set.

        Every one of them read ``self.type_id`` directly, so a two-record
        create raised "Expected singleton".
        """
        type_a, type_b = self.env["date.range.type"].create(
            [
                {
                    "name": "A",
                    "allow_overlap": True,
                    "name_prefix": "AAA",
                    "duration_count": 1,
                    "unit_of_time": str(MONTHLY),
                },
                {
                    "name": "B",
                    "allow_overlap": True,
                    "name_prefix": "BBB",
                    "duration_count": 7,
                    "unit_of_time": str(MONTHLY),
                },
            ]
        )
        wizards = self.generator.create(
            [{"type_id": type_a.id, "count": 1}, {"type_id": type_b.id, "count": 1}]
        )
        self.env.flush_all()
        self.assertEqual(wizards.mapped("name_prefix"), ["AAA", "BBB"])
        self.assertEqual(wizards.mapped("duration_count"), [1, 7])

    def test_incomplete_settings_report_what_is_missing(self):
        wizard = self.generator.create({"count": 2})
        with self.assertRaisesRegex(UserError, "date range type"):
            wizard.action_apply()

    def test_preview_agrees_with_generated_names(self):
        """The type preview, the wizard preview and the result all agree.

        The type used to run its own preview implementation that could not know
        how many ranges there would be, so it promised ``Q1`` where the wizard
        and the created ranges said ``Q01``.
        """
        dr_type = self.env["date.range.type"].create(
            {
                "name": "Padded",
                "allow_overlap": True,
                "name_prefix": "Q",
                "duration_count": 1,
                "unit_of_time": str(MONTHLY),
                "autogeneration_date_start": "2052-01-01",
                "autogeneration_count": 1,
                "autogeneration_unit": str(MONTHLY),
            }
        )
        wizard = self.generator.create(
            {"type_id": dr_type.id, "count": 12, "date_start": "2052-01-01"}
        )
        wizard.action_apply()
        names = (
            self.env["date.range"]
            .search([("type_id", "=", dr_type.id)], order="date_start")
            .mapped("name")
        )
        self.assertEqual(names[0], "Q01")
        self.assertEqual(names[-1], "Q12")

    def test_generator_form(self):
        """Test validation and onchange functionality"""
        form = Form(self.env["date.range.generator"])
        form.type_id = self.type
        form.unit_of_time = str(MONTHLY)
        form.duration_count = 10
        form.date_end = "2021-01-01"
        # Setting count clears date_end
        form.count = 10
        self.assertFalse(form.date_end)
        # Setting date_end clears count
        form.date_end = "2021-01-01"
        self.assertFalse(form.count)
        form.count = 10
        form.name_prefix = "PREFIX"
        # An invalid name_expr is reported in the preview rather than raised,
        # so the form stays editable; generation still refuses it.
        form.name_expr = "'not valid"
        self.assertIn("Invalid name expression", form.range_name_preview)
        with self.assertRaisesRegex(UserError, "Invalid name expression"):
            form.save().action_apply()
        # Setting name_expr clears name_prefix
        form.name_expr = "'PREFIX%s' % index"
        self.assertFalse(form.name_prefix)
        self.assertEqual(form.range_name_preview, "PREFIX01")
        wizard = form.save()

        # Cannot generate ranges without count and without date_end.
        # action_apply reports the missing settings as a UserError.
        wizard.date_end = False
        wizard.count = False
        with self.assertRaisesRegex(UserError, "end date or number of ranges"):
            wizard.action_apply()

        wizard.count = 10
        # Cannot generate ranges without a prefix and without an expression
        wizard.name_expr = False
        wizard.name_prefix = False
        with self.assertRaisesRegex(UserError, "name prefix or name expression"):
            wizard.action_apply()
