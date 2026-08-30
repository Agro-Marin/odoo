"""Tests for the partner res.partner overrides."""

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResPartner(TransactionCase):
    def test_get_backend_root_menu_ids_includes_partner_menu(self):
        """res.partner's backend root menu includes partner's own menu."""
        menu_ids = self.env["res.partner"]._get_backend_root_menu_ids()
        self.assertIn(self.env.ref("partner.partner_menu_root").id, menu_ids)


@tagged("post_install", "-at_install")
class TestSearchAge(TransactionCase):
    """`age` is computed, not stored, and must still be answerable in SQL.

    The mapping runs backwards -- an older contact was born earlier -- so every
    operator inverts, and the strict forms shift a year because "older than 30"
    means "has completed 31".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        today = fields.Date.today()
        cls.ages = {}
        for age in (17, 18, 19, 40):
            cls.ages[age] = cls.Partner.create(
                {
                    "name": f"Aged {age}",
                    # Half a year in, so no test sits on a birthday boundary.
                    "birthdate": today - relativedelta(years=age, months=6),
                }
            )
        cls.undated = cls.Partner.create({"name": "No birthdate"})

    def _found(self, operator, value):
        ids = [partner.id for partner in self.ages.values()] + self.undated.ids
        found = self.Partner.search([("id", "in", ids), ("age", operator, value)])
        return {partner.age for partner in found}

    def test_the_computed_age_is_what_it_claims(self):
        for age, partner in self.ages.items():
            self.assertEqual(partner.age, age)
        self.assertFalse(self.undated.age)

    def test_at_least_and_strictly_older(self):
        self.assertEqual(self._found(">=", 18), {18, 19, 40})
        self.assertEqual(self._found(">", 18), {19, 40})

    def test_at_most_and_strictly_younger(self):
        self.assertEqual(self._found("<", 18), {17})
        self.assertEqual(self._found("<=", 18), {17, 18})

    def test_an_exact_age_is_a_one_year_window(self):
        self.assertEqual(self._found("=", 18), {18})
        self.assertEqual(self._found("!=", 18), {17, 19, 40})

    def test_a_partner_without_a_birthdate_matches_no_comparison(self):
        """It has no age, so it is absent from a comparison and its negation."""
        for operator, value in ((">=", 0), ("<", 200), ("=", 0), ("!=", 0)):
            self.assertNotIn(
                self.undated,
                self.Partner.search([("age", operator, value)]),
                f"a partner with no birthdate was returned by age {operator} {value}",
            )

    def test_an_unsupported_operator_says_so(self):
        with self.assertRaises(NotImplementedError):
            self.Partner.search([("age", "like", "18")])
