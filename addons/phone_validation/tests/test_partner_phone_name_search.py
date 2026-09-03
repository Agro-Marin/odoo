from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import OrderedSet


@tagged("post_install", "-at_install")
class TestPartnerPhoneNameSearch(TransactionCase):
    """Resolving a contact from a phone number typed into a Many2one.

    The search panel already finds a number: ``phone_validation`` swaps the
    ``phone`` field of the contact search view for ``phone_mobile_search``,
    which normalises digits on both sides and is index-backed. ``name_search``
    is the other path -- every Many2one autocomplete in the system -- and it
    reads ``_rec_names_search``, which named no phone field at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Zuleika Vandenbroucke",
                "phone": "+32 485 60 70 80",
                "mobile": "+32 470 11 22 33",
            }
        )

    def test_the_phone_field_is_searched_without_displacing_the_others(self):
        """The phone entry is added to what base already searches, not swapped in."""
        names = self.env["res.partner"]._rec_names_search

        self.assertIn("phone_mobile_search", names)
        self.assertIn("complete_name", names)
        self.assertIn("email", names)

    def test_a_contact_is_found_by_its_phone_number(self):
        """The digits of the landline resolve the contact."""
        found = self.env["res.partner"].name_search("485607080")

        self.assertIn(self.partner.id, [pid for pid, _ in found])

    def test_a_contact_is_found_by_its_mobile_number(self):
        """A model with both numbers is searched on both, not only on phone."""
        found = self.env["res.partner"].name_search("470112233")

        self.assertIn(self.partner.id, [pid for pid, _ in found])

    def test_the_punctuation_of_the_typed_number_does_not_matter(self):
        """Spaces and the country prefix are stripped from the term as well."""
        found = self.env["res.partner"].name_search("+32 485 60 70 80")

        self.assertIn(self.partner.id, [pid for pid, _ in found])

    def test_searching_by_name_still_works(self):
        """The added entry does not disturb the name path it is ORed with."""
        found = self.env["res.partner"].name_search("Vandenbroucke")

        self.assertIn(self.partner.id, [pid for pid, _ in found])

    def test_an_unrelated_number_does_not_match(self):
        """Normalisation must not collapse every number onto every other."""
        found = self.env["res.partner"].name_search("999888777")

        self.assertNotIn(self.partner.id, [pid for pid, _ in found])

    def test_a_term_shorter_than_the_phone_minimum_still_resolves_a_contact(self):
        """Typing one or two letters must not be refused by the phone entry.

        A Many2one autocomplete queries on the first keystroke, and the phone
        search rejects a term below its minimum length. Left in the OR, that
        rejection failed the whole lookup instead of the phone part of it.
        """
        for term in ("Z", "Zu"):
            with self.subTest(term=term):
                found = self.env["res.partner"].name_search(term)

                self.assertIn(self.partner.id, [pid for pid, _ in found])

    def test_a_short_term_is_refused_when_the_phone_field_is_searched_directly(self):
        """Dropping the entry from name_search does not relax the field itself."""
        with self.assertRaises(UserError):
            self.env["res.partner"].search([("phone_mobile_search", "ilike", "Zu")])

    def test_a_short_term_does_not_break_an_equality_search(self):
        """The `=` path reaches the phone search too, and must be guarded alike."""
        found = self.env["res.partner"].name_search("Zu", operator="=")

        self.assertEqual([pid for pid, _ in found], [])

    def test_a_short_term_does_not_break_a_negated_search(self):
        """`not ilike` aggregates with AND, so the entry is dropped there too."""
        found = self.env["res.partner"].name_search("Zu", operator="not ilike")

        self.assertNotIn(self.partner.id, [pid for pid, _ in found])

    def test_an_empty_term_is_not_treated_as_too_short(self):
        """The phone search reads a void term as a set/unset test, not a refusal."""
        self.assertFalse(self.env["res.partner"]._phone_term_too_short(""))
        self.assertFalse(self.env["res.partner"]._phone_term_too_short(False))
        self.assertFalse(self.env["res.partner"]._phone_term_too_short(True))

    def test_a_collection_of_terms_is_too_short_when_any_of_them_is(self):
        """`in` passes a collection, and one short member is enough to refuse.

        The collection the domain optimiser hands over is an ``OrderedSet``,
        not a list, so a membership test written against the builtins alone
        reads every ``in`` term as a single unrecognised value and lets it by.
        """
        partners = self.env["res.partner"]

        for collect in (list, tuple, set, frozenset, OrderedSet):
            with self.subTest(collection=collect.__name__):
                self.assertTrue(
                    partners._phone_term_too_short(collect(["Zuleika", "Zu"]))
                )
                self.assertFalse(
                    partners._phone_term_too_short(collect(["Zuleika", "Vanden"]))
                )
