from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAddressExtendedOnchanges(TransactionCase):
    """res.city display name and res.partner city/country onchanges."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country = cls.env.ref("base.us")
        cls.state = cls.env["res.country.state"].search(
            [("country_id", "=", cls.country.id)], limit=1
        )
        cls.city = cls.env["res.city"].create(
            {
                "name": "Springfield",
                "zipcode": "62701",
                "country_id": cls.country.id,
                "state_id": cls.state.id,
            }
        )

    def test_city_display_name_with_zip(self):
        """A city with a zip shows "name (zip)"."""
        self.assertIn("Springfield (62701)", str(self.city.display_name))

    def test_city_display_name_without_zip(self):
        """A city without a zip shows only the name (boundary)."""
        city = self.env["res.city"].create(
            {"name": "Nozip", "country_id": self.country.id}
        )
        self.assertIn("Nozip", str(city.display_name))
        self.assertNotIn("(", str(city.display_name))

    def test_onchange_city_id_populates_address(self):
        """Selecting a city_id fills city, zip and state on the partner."""
        partner = self.env["res.partner"].new({"city_id": self.city.id})
        partner._onchange_city_id()
        self.assertEqual(partner.city, "Springfield")
        self.assertEqual(partner.zip, "62701")
        self.assertEqual(partner.state_id, self.state)

    def test_onchange_country_clears_mismatched_city(self):
        """Changing country to one that mismatches the city clears city_id."""
        other = self.env["res.country"].search([("id", "!=", self.country.id)], limit=1)
        partner = self.env["res.partner"].new(
            {"city_id": self.city.id, "country_id": other.id}
        )
        partner._onchange_country_id()
        self.assertFalse(partner.city_id)

    def test_onchange_country_clears_stale_city_zip_state(self):
        """Clearing a mismatched city_id also clears city/zip/state_id."""
        other = self.env["res.country"].search([("id", "!=", self.country.id)], limit=1)
        partner = self.env["res.partner"].new({"city_id": self.city.id})
        partner._onchange_city_id()
        self.assertEqual(partner.city, "Springfield")
        self.assertEqual(partner.zip, "62701")

        partner.country_id = other
        partner._onchange_country_id()
        self.assertFalse(partner.city_id)
        self.assertFalse(partner.city)
        self.assertFalse(partner.zip)
        self.assertFalse(partner.state_id)
