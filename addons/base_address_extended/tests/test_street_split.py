"""Tests for the extended street split/compose fields on partners."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStreetSplit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]

    def test_street_splits_into_subfields(self):
        """Setting street populates the name/number sub-fields."""
        partner = self.Partner.create(
            {"name": "Split partner", "street": "Reforma 222"}
        )
        self.assertEqual(partner.street_name, "Reforma")
        self.assertEqual(partner.street_number, "222")

    def test_subfields_compose_into_street(self):
        """Writing the sub-fields rebuilds the full street with a door."""
        partner = self.Partner.create({"name": "Compose partner"})
        partner.write(
            {
                "street_name": "Insurgentes",
                "street_number": "1601",
                "street_number2": "4B",
            }
        )
        self.assertEqual(partner.street, "Insurgentes 1601 - 4B")

    def test_compose_without_door(self):
        """Without a door number the street has no separator (boundary)."""
        partner = self.Partner.create({"name": "No door partner"})
        partner.write({"street_name": "Juarez", "street_number": "10"})
        self.assertEqual(partner.street, "Juarez 10")

    def test_get_street_split_payload(self):
        """_get_street_split returns the three sub-fields."""
        partner = self.Partner.create(
            {"name": "Payload partner", "street": "Madero 5 - 2"}
        )
        payload = partner._get_street_split()
        self.assertEqual(payload["street_name"], "Madero")
        self.assertEqual(payload["street_number"], "5")
        self.assertEqual(payload["street_number2"], "2")
