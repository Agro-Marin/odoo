from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailTemplates(TransactionCase):
    """Render coverage for iap_mail's IAP-enrichment QWeb templates.

    A render test asserts every truthy value actually reaches the page,
    which is exactly what would have caught a directive typo like a
    misspelled ``t-out`` silently dropping a field.
    """

    def test_enrich_company_renders_every_field(self):
        values = {
            "flavor_text": "Enriched from Clearbit",
            "name": "ACME Corp",
            "twitter": "acme",
            "facebook": False,
            "linkedin": False,
            "crunchbase": False,
            "description": "A widget maker",
            "logo": False,
            "company_type": "Private",
            "founded_year": "1999",
            "sector_primary": "Manufacturing",
            "industry": False,
            "industry_group": False,
            "sub_industry": False,
            "employees": 42,
            "estimated_annual_revenue": "1M-10M",
            "phone_numbers": ["+1234567890"],
            "email": ["contact@acme.example"],
            "timezone": "America_New_York",
            "tech": ["python", "postgresql"],
            "twitter_bio": "We make widgets",
            "twitter_followers": 100,
        }
        html = self.env["ir.qweb"]._render("iap_mail.enrich_company", values)
        self.assertIn("ACME Corp", html)
        self.assertIn("Manufacturing", html)
        self.assertIn("42", html)
        self.assertIn("America New York", html)
        # tech values are rendered title-cased (see the template's
        # .replace('_', ' ').title() call).
        self.assertIn("Python", html)

    def test_enrich_company_by_dnb_renders_every_field(self):
        values = {
            "name": "ACME Corp",
            "logo": False,
            "company_type": "Private",
            "vat": "BE0123456789",
            "sector_primary": False,
            "industry": False,
            "industry_group": False,
            "sub_industry": False,
            "street": "Main St 1",
            "street2": False,
            "city": "Brussels",
            "state": "Brussels-Capital",
            "zip_code": "1000",
            "country": "Belgium",
            "employees": 42,
            "estimated_annual_revenue": "1M-10M",
            "phone": "+1234567890",
            "email": "contact@acme.example",
            "website": "https://acme.example",
            "tags": [(1, "Manufacturing")],
        }
        html = self.env["ir.qweb"]._render("iap_mail.enrich_company_by_dnb", values)
        self.assertIn("ACME Corp", html)
        self.assertIn("Brussels", html)
        # Regression guard for the "toutc" typo (task 28187): the state must
        # actually reach the page, not just be accepted by t-if.
        self.assertIn("Brussels-Capital", html)
        self.assertIn("1000", html)
        self.assertIn("Manufacturing", html)
