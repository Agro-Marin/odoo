from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestResCountryState(TransactionCase):
    def test_find_by_name(self):
        glorious_arstotzka = self.env["res.country"].create(
            {
                "name": "Arstotzka",
                "code": "AA",
            }
        )
        altan = self.env["res.country.state"].create(
            {
                "country_id": glorious_arstotzka.id,
                "code": "AL",
                "name": "Altan",
            }
        )

        for name in [
            altan.name,
            altan.display_name,
            "Altan(AA)",
            "Altan ( AA )",
            "Altan (Arstotzka)",
            "Altan (Arst)",
        ]:
            with self.subTest(name):
                self.assertEqual(
                    self.env["res.country.state"].name_search(name, operator="="),
                    [(altan.id, altan.display_name)],
                )

        vescillo = self.env["res.country.state"].create(
            {
                "country_id": glorious_arstotzka.id,
                "code": "VE",
                "name": "Vescillo (Vesilo)",
            }
        )
        for name in [
            vescillo.name,
            vescillo.display_name,
            "vescillo",
            "vesilo",
            "vescillo (AA)",
            "vesilo (AA)",
            "vesilo (Arstotzka)",
        ]:
            with self.subTest(name):
                self.assertEqual(
                    self.env["res.country.state"].name_search(name, operator="ilike"),
                    [(vescillo.id, vescillo.display_name)],
                )

        for name in [
            [altan.name],
            [altan.display_name],
            ["Altan(AA)"],
            ["Altan ( AA )"],
            ["Altan (Arstotzka)"],
            ["Altan (Arst)"],
        ]:
            with self.subTest(name):
                self.assertEqual(
                    self.env["res.country.state"].name_search(name, operator="in"),
                    [(altan.id, altan.display_name)],
                )


@tagged("-at_install", "post_install")
class TestGetAddressFields(TransactionCase):
    def test_get_address_fields_default_format(self):
        country = self.env["res.country"].create({"name": "Arstotzka", "code": "AA"})
        self.assertEqual(
            country.get_fields_address(),
            ["street", "street2", "city", "state_code", "zip", "country_name"],
        )

    def test_get_address_fields_empty_format(self):
        country = self.env["res.country"].create(
            {"name": "Arstotzka", "code": "AA", "address_format": False}
        )
        self.assertFalse(country.address_format)
        self.assertEqual(country.get_fields_address(), [])

    def test_get_address_fields_ignores_literal_parentheses(self):
        country = self.env["res.country"].create(
            {
                "name": "Arstotzka",
                "code": "AA",
                "address_format": "%(street)s (near the park)\n"
                "%(zip)s %(city)s (P.O. Box)\n%(country_name)s",
            }
        )
        self.assertEqual(
            country.get_fields_address(),
            ["street", "zip", "city", "country_name"],
        )
