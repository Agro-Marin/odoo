from odoo.tests import common, tagged

from odoo.addons.partner_autocomplete.tests.common import MockIAPPartnerAutocomplete

# Two distinct, valid, minimal 1x1 PNGs (base64) used to tell a "manual" logo
# apart from an "IAP-fetched" one without relying on byte-for-byte equality
# with the un-reprocessed input (Odoo re-encodes image fields on write).
MANUAL_LOGO = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
IAP_LOGO = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@tagged("post_install", "-at_install")
class TestResCompany(common.TransactionCase, MockIAPPartnerAutocomplete):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._init_mock_partner_autocomplete()

    def test_enrich(self):
        company = self.env["res.company"].create({"name": "Test Company 1"})
        with self.mockPartnerAutocomplete():
            res = company._enrich()
            self.assertFalse(res)

        company.write({"email": "friedrich@heinrich.de"})
        with self.mockPartnerAutocomplete():
            # asserts are synchronized with default mock values
            res = company._enrich()
            self.assertTrue(res)
            self.assertEqual(company.country_id, self.env.ref("base.de"))

    def test_enrich_does_not_overwrite_manual_logo(self):
        """`_enrich()` must not clobber a manually-uploaded company logo."""
        company = self.env["res.company"].create({"name": "Test Company 2"})
        company.partner_id.image_1920 = MANUAL_LOGO
        manual_logo_processed = company.partner_id.image_1920

        company.write({"email": "friedrich@heinrich.de"})
        with self.mockPartnerAutocomplete(default_data={"image_1920": IAP_LOGO}):
            res = company._enrich()
            self.assertTrue(res)

        self.assertEqual(company.partner_id.image_1920, manual_logo_processed)

    def test_enrich_ignores_fields_outside_allowlist(self):
        """`_enrich()` must not write partner fields outside its enrichment
        allowlist, even when the IAP response happens to include a key that
        matches a real `res.partner` field name.
        """
        company = self.env["res.company"].create({"name": "Test Company 3"})
        company.write({"email": "friedrich@heinrich.de"})
        with self.mockPartnerAutocomplete(
            default_data={
                "function": "Chief Duck Herder",
                "comment": "should not land on the partner",
            }
        ):
            res = company._enrich()
            self.assertTrue(res)

        self.assertFalse(company.partner_id.function)
        self.assertFalse(company.partner_id.comment)

    def test_extract_company_domain(self):
        company_1 = self.env["res.company"].create({"name": "Test Company 1"})

        company_1.website = "http://www.info.proximus.be/faq/test"
        self.assertEqual(company_1._get_company_domain_name(), "proximus.be")

        company_1.email = "info@waterlink.be"
        self.assertEqual(company_1._get_company_domain_name(), "waterlink.be")

        company_1.website = False
        company_1.email = False
        self.assertEqual(company_1._get_company_domain_name(), False)

        company_1.email = "at@"
        self.assertEqual(company_1._get_company_domain_name(), False)

        company_1.website = "http://superFalsyWebsiteName"
        self.assertEqual(company_1._get_company_domain_name(), False)

        company_1.website = "http://www.superwebsite.com"
        self.assertEqual(company_1._get_company_domain_name(), "superwebsite.com")

        company_1.website = "http://superwebsite.com"
        self.assertEqual(company_1._get_company_domain_name(), "superwebsite.com")

        company_1.website = "http://localhost:8069/%7Eguido/Python.html"
        self.assertEqual(company_1._get_company_domain_name(), False)

        company_1.website = "http://runbot.odoo.com"
        self.assertEqual(company_1._get_company_domain_name(), "odoo.com")

        company_1.website = "http://www.example.com/biniou"
        self.assertEqual(company_1._get_company_domain_name(), False)

        company_1.website = "http://www.cwi.nl:80/%7Eguido/Python.html"
        self.assertEqual(company_1._get_company_domain_name(), "cwi.nl")
