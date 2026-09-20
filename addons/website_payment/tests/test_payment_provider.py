from odoo.tests import tagged

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.payment.tests.common import PaymentCommon


@tagged("post_install", "-at_install")
class TestWebsitePaymentProvider(PaymentCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")
        cls.other_website = cls.env["website"].create({"name": "Other website"})

    def test_compatible_providers_filters_foreign_website(self):
        self.provider.website_id = self.other_website
        report = {}
        providers = self.env["payment.provider"]._get_compatible_providers(
            self.company.id,
            self.partner.id,
            self.amount,
            website_id=self.website.id,
            report=report,
        )
        self.assertNotIn(self.provider, providers)

        self.provider.website_id = self.website
        providers = self.env["payment.provider"]._get_compatible_providers(
            self.company.id,
            self.partner.id,
            self.amount,
            website_id=self.website.id,
        )
        self.assertIn(self.provider, providers)

    def test_compatible_providers_reports_incompatibility(self):
        self.provider.website_id = self.other_website
        report = {}
        self.env["payment.provider"]._get_compatible_providers(
            self.company.id,
            self.partner.id,
            self.amount,
            website_id=self.website.id,
            report=report,
        )
        self.assertTrue(report, "the report should mention the dropped provider")

    def test_copy_propagates_website(self):
        self.provider.website_id = self.website
        copy = self.provider.copy()
        self.assertEqual(copy.website_id, self.website)

    def test_copy_respects_explicit_website_default(self):
        self.provider.website_id = self.website
        copy = self.provider.copy(default={"website_id": False})
        self.assertFalse(copy.website_id)

    def test_settings_domain_scopes_to_website(self):
        settings = self.env["res.config.settings"].new(
            {
                "website_id": self.website.id,
            }
        )
        domain = settings._get_domain_active_providers()
        self.assertIn(("website_id", "=", self.website.id), list(domain))

    def test_base_url_follows_request_root(self):
        with MockRequest(self.env, website=self.website):
            url = self.provider.get_base_url()
        self.assertTrue(url.startswith("http"))
