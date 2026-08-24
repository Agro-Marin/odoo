from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestFiscalCountryCodes(AccountTestInvoicingCommon):
    """`fiscal_country_codes` drives `invisible=` expressions in localisation
    views, so every model exposing it has to answer for the companies that are
    active right now.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.setup_other_company(
            name="Fiscal Codes Co", country_id=cls.quick_ref("base.be").id
        )["company"]
        cls.both_companies = cls.env.company | cls.other_company

    def _records_exposing_the_field(self):
        return {
            "product.template": self.env["product.template"].create(
                {"name": "ZZ Fiscal Codes"}
            ),
            "res.partner": self.env["res.partner"].create({"name": "ZZ Fiscal Codes"}),
            "uom.uom": self.env.ref("uom.product_uom_unit"),
            "res.currency": self.env.company.currency_id,
            "account.payment.term": self.env["account.payment.term"].create(
                {
                    "name": "ZZ Fiscal Codes",
                    "line_ids": [(0, 0, {"value": "percent", "value_amount": 100.0})],
                }
            ),
        }

    def test_control_the_two_companies_have_different_fiscal_countries(self):
        self.assertNotEqual(
            self.env.company.account_fiscal_country_id,
            self.other_company.account_fiscal_country_id,
            "control: the widening below only shows anything if the second"
            " company adds a country the first does not have",
        )

    def test_every_model_answers_for_the_active_companies(self):
        wanted = self.other_company.account_fiscal_country_id.code
        for model_name, record in self._records_exposing_the_field().items():
            with self.subTest(model=model_name):
                narrow = record.with_context(
                    allowed_company_ids=self.env.company.ids
                ).fiscal_country_codes
                self.assertNotIn(
                    wanted,
                    narrow or "",
                    f"{model_name}: one company active must not report the other's",
                )
                wide = record.with_context(
                    allowed_company_ids=self.both_companies.ids
                ).fiscal_country_codes
                self.assertIn(
                    wanted,
                    wide or "",
                    f"{model_name}: widening the active companies must be picked"
                    " up without an explicit invalidation",
                )

    def test_a_company_bound_record_answers_for_its_own_company(self):
        partner = self.env["res.partner"].create(
            {"name": "ZZ Bound", "company_id": self.other_company.id}
        )
        self.assertEqual(
            partner.with_context(
                allowed_company_ids=self.both_companies.ids
            ).fiscal_country_codes,
            self.other_company.account_fiscal_country_id.code,
        )

    def test_a_partner_adds_its_own_country(self):
        partner = self.env["res.partner"].create(
            {"name": "ZZ Country", "country_id": self.quick_ref("base.fr").id}
        )
        self.assertIn("FR", partner.fiscal_country_codes)
        self.assertIn(
            self.env.company.account_fiscal_country_id.code,
            partner.fiscal_country_codes,
        )
