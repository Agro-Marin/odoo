# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosLoadScoping(TestPoSCommon):
    """The session payload must only carry the countries and states it can reach.

    Loading `res.country` and `res.country.state` unfiltered ships ~2200 rows on
    every cold load and every IndexedDB reset, a fixed cost that dwarfs the rest of
    the payload on a small shop.
    """

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.session = self.open_new_session()

    def _load(self, models_to_load=None):
        return self.session.load_data(models_to_load or [])

    @property
    def _company_country_ids(self):
        return {
            self.company.country_id.id,
            self.company.account_fiscal_country_id.id,
        } - {False}

    def test_countries_scoped_to_loaded_partners_and_company(self):
        country = self.env.ref("base.mx")
        state = self.env["res.country.state"].search(
            [("country_id", "=", country.id)], limit=1
        )
        self.env["res.partner"].create(
            {
                "name": "Foreign Customer",
                "country_id": country.id,
                "state_id": state.id,
            }
        )

        data = self._load()
        loaded = {record["id"] for record in data["res.country"]}
        expected = {
            partner["country_id"]
            for partner in data["res.partner"]
            if partner["country_id"]
        } | self._company_country_ids

        self.assertEqual(loaded, expected)
        self.assertLess(
            len(loaded),
            self.env["res.country"].search_count([]),
            "the whole country table must not be shipped to the session",
        )

    def test_states_scoped_to_loaded_countries(self):
        country = self.env.ref("base.mx")
        state = self.env["res.country.state"].search(
            [("country_id", "=", country.id)], limit=1
        )
        self.env["res.partner"].create(
            {
                "name": "Foreign Customer",
                "country_id": country.id,
                "state_id": state.id,
            }
        )

        data = self._load()
        loaded_countries = {record["id"] for record in data["res.country"]}
        loaded_states = self.env["res.country.state"].browse(
            record["id"] for record in data["res.country.state"]
        )

        # The partner's own state comes along, and nothing from a country the
        # session never loaded.
        self.assertIn(state.id, loaded_states.ids)
        self.assertFalse(
            loaded_states.filtered(lambda s: s.country_id.id not in loaded_countries)
        )
        self.assertLess(
            len(loaded_states), self.env["res.country.state"].search_count([])
        )

    def test_company_country_always_loaded(self):
        """The receipt prints the company address and its country `vat_label`.

        `test_partial_load_without_partners` covers the same guarantee with no
        partner loaded at all, which is what isolates the company-country term.
        """
        data = self._load()
        self.assertIn(
            self.company.country_id.id, {record["id"] for record in data["res.country"]}
        )

    def test_company_state_always_loaded(self):
        """The receipt prints `company.state_id.code`."""
        state = self.env["res.country.state"].create(
            {
                "name": "PoS State",
                "code": "PS",
                "country_id": self.company.country_id.id,
            }
        )
        self.company.write({"state_id": state.id})

        data = self._load()
        self.assertIn(state.id, {record["id"] for record in data["res.country.state"]})

    def test_partner_state_without_country_loaded(self):
        """A state is reachable through a partner even if its country is not."""
        state = self.env["res.country.state"].search(
            [("country_id", "=", self.env.ref("base.mx").id)], limit=1
        )
        partner = self.env["res.partner"].create(
            {"name": "Stateful Customer", "state_id": state.id}
        )

        data = self._load()
        if partner.id not in {record["id"] for record in data["res.partner"]}:
            self.skipTest("partner loading is limited and dropped the test partner")
        self.assertIn(state.id, {record["id"] for record in data["res.country.state"]})

    def test_partial_load_without_partners(self):
        """A partial model list must degrade, not raise: `res.partner` is absent."""
        data = self._load(["res.country", "res.country.state"])

        self.assertEqual(
            {record["id"] for record in data["res.country"]},
            self._company_country_ids,
        )
