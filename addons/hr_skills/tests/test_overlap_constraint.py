from datetime import date

from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests import tagged

from .common import SkillsCase


@tagged("post_install", "-at_install")
class TestOverlapConstraintTotality(SkillsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Overlap employee"})

    def test_a_batch_mixing_a_bounded_and_an_open_ended_skill_validates(self):
        """Two edits to one skill in one batch, one of them open-ended.

        The matching domain is a single OR across the whole batch, so a stored
        row can match because of the bounded values and then be date-compared
        against the open-ended ones. Comparing a date to `valid_to = False`
        raised TypeError -- a 500 out of a constraint whose job is to answer
        with a message.
        """
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.employee.id,
                "skill_id": self.skill_piano.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": date(2026, 11, 1),
                "valid_to": False,
            },
        )
        self.env.flush_all()

        with self.assertRaises(ValidationError):
            self.env["hr.employee.skill"].create(
                [
                    {
                        "employee_id": self.employee.id,
                        "skill_id": self.skill_piano.id,
                        "skill_level_id": self.level_novice.id,
                        "skill_type_id": self.skill_type.id,
                        "valid_from": date(2026, 10, 16),
                        "valid_to": date(2027, 5, 29),
                    },
                    {
                        "employee_id": self.employee.id,
                        "skill_id": self.skill_piano.id,
                        "skill_level_id": self.level_expert.id,
                        "skill_type_id": self.skill_type.id,
                        "valid_from": date(2026, 2, 15),
                        "valid_to": False,
                    },
                ],
            )

    def test_covering_a_missing_date_matches_what_the_domain_does(self):
        """`_covers_date` must answer False for an absent date, not raise.

        The domain it mirrors compiles `valid_from <= False` to WHERE FALSE, so
        False is the answer that keeps the Python side and the SQL side saying
        the same thing.
        """
        stored = self.env["hr.employee.skill"].create(
            {
                "employee_id": self.employee.id,
                "skill_id": self.skill_guitar.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": date(2026, 1, 1),
                "valid_to": False,
            },
        )
        model = self.env["hr.employee.skill"]

        self.assertFalse(model._covers_date(stored, False))
        self.assertTrue(model._covers_date(stored, date(2026, 6, 1)))
        self.assertFalse(model._covers_date(stored, date(2025, 6, 1)))

        query = model._search(Domain("valid_from", "<=", False))
        self.assertFalse(
            list(query), "the domain selects nothing, so neither may the predicate"
        )

    def test_the_error_names_the_skill_rather_than_dumping_a_vals_dict(self):
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.employee.id,
                "skill_id": self.skill_guitar.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": date(2026, 1, 1),
                "valid_to": False,
            },
        )
        self.env.flush_all()

        with self.assertRaises(ValidationError) as caught:
            self.env["hr.employee.skill"].create(
                {
                    "employee_id": self.employee.id,
                    "skill_id": self.skill_guitar.id,
                    "skill_level_id": self.level_expert.id,
                    "skill_type_id": self.skill_type.id,
                    "valid_from": date(2026, 6, 1),
                    "valid_to": False,
                },
            )
        message = str(caught.exception)
        self.assertIn("Guitar", message)
        self.assertNotIn("employee_id", message)
        self.assertNotIn("{", message)
