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
        cls.other_company = cls.setup_other_company(name="Fiscal Codes Co")["company"]
        # Creating the company IN another country would demand that country's
        # localisation module, and `AccountTestInvoicingCommon` skips the whole
        # class when it is absent -- silently, since a skipped setUpClass reports
        # as a pass. Only the fiscal country matters here, so it is written
        # directly.
        cls.other_company.account_fiscal_country_id = cls.quick_ref("base.be")
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
        # Not a partner: `res.partner` also appends its own `country_code`, which
        # a new partner inherits from the company creating it, so the answer is
        # legitimately two codes there. `account.payment.term` carries a
        # `company_id` and nothing else.
        term = self.env["account.payment.term"].create(
            {
                "name": "ZZ Bound",
                "company_id": self.other_company.id,
                "line_ids": [(0, 0, {"value": "percent", "value_amount": 100.0})],
            }
        )
        self.assertEqual(
            term.with_context(
                allowed_company_ids=self.both_companies.ids
            ).fiscal_country_codes,
            self.other_company.account_fiscal_country_id.code,
        )

    def test_a_company_bound_partner_leaves_out_the_other_companys_country(self):
        partner = self.env["res.partner"].create(
            {
                "name": "ZZ Bound Partner",
                "company_id": self.other_company.id,
                "country_id": False,
            }
        )
        self.assertFalse(partner.country_code, "control: no country of its own")
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

    # A `related` is a legitimate way to expose the field: it forwards another
    # model's answer rather than recomputing it. The one model that names the
    # field for something else is listed, not silently tolerated.
    _NOT_THE_ACTIVE_COMPANIES_ANSWER = {
        # related="company_country_id.code": this fiscal position's own company's
        # country, a single code, not the active companies' set. The four
        # localisation views that read it here want exactly that, so it is left
        # alone -- but the shared name means the same expression says two things
        # depending on which form it sits on.
        "account.fiscal.position",
    }

    def test_control_the_registry_exposes_the_field_somewhere(self):
        exposing = [
            name
            for name in self.env.registry.models
            if "fiscal_country_codes" in self.env[name]._fields
        ]
        self.assertGreater(
            len(exposing),
            5,
            "control: this guard proves nothing if it inspects an empty set",
        )

    def test_no_model_recomputes_fiscal_country_codes_on_its_own(self):
        """The field was defined five times in `account` alone and four more in
        localisations, one of them as a `default=` on an unstored field, which
        does not re-evaluate when the active companies change. Every definition
        now comes from the mixin or forwards one that does.
        """
        offenders = []
        for name in sorted(self.env.registry.models):
            model = self.env[name]
            field = model._fields.get("fiscal_country_codes")
            if field is None or name in self._NOT_THE_ACTIVE_COMPANIES_ANSWER:
                continue
            if hasattr(model, "_get_fiscal_country_companies"):
                continue
            if field.related and field.related.rsplit(".", 1)[-1] == (
                "fiscal_country_codes"
            ):
                continue
            offenders.append(f"{name}.fiscal_country_codes")
        self.assertFalse(
            offenders,
            "these declare the field without inheriting mixin.fiscal.country.codes"
            " and without forwarding a field that does; a `default=` in particular"
            " keeps a value that no longer matches allowed_company_ids",
        )
