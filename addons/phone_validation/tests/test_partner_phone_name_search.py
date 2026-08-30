from odoo.tests import TransactionCase, tagged


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
