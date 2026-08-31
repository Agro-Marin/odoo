from odoo.tests import Form, TransactionCase, tagged

SOCIAL_FIELDS = [
    "social_twitter",
    "social_facebook",
    "social_github",
    "social_linkedin",
    "social_youtube",
    "social_instagram",
    "social_tiktok",
    "social_discord",
]


@tagged("post_install", "-at_install")
class TestSocialMedia(TransactionCase):
    def test_social_fields_readable_and_writable(self):
        """The 8 social_* fields this module adds to res.company round-trip."""
        company = self.env.company
        values = {name: f"https://example.com/{name}" for name in SOCIAL_FIELDS}
        company.write(values)
        for name, value in values.items():
            self.assertEqual(company[name], value)

    def test_company_form_renders(self):
        """The xpath replacing base's empty social_media placeholder still
        matches: building the form must not raise, and the 8 fields must be
        part of its field list.

        The group itself is gated by ``groups="base.group_no_one"``, which
        the view engine special-cases as the debug-mode toggle (it checks
        ``request.session.debug``, not plain group membership — see
        ``ResUsers._has_group_effective``), so the fields are always
        rendered invisible outside of an actual HTTP debug session. Writing
        through them here is not obtainable; the xpath resolving without a
        "field not found" error, before that debug postprocessing, is the
        part this test can prove.
        """
        form = Form(self.env.company)
        for field_name in SOCIAL_FIELDS:
            self.assertIn(field_name, form._view["fields"])
