from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailingDynamicFields(TransactionCase):
    """`mailing.mailing` declares which of its fields hold a template.

    Inferring the set from the field type also named `mailing_domain` — a
    recipient filter no engine renders — so a domain whose literal happened to
    contain `{{ }}` was refused to a non-editor with "Only members of Mail
    Template Editor group are allowed to edit templates containing sensible
    placeholders".
    """

    def test_the_recipient_filter_is_not_a_template(self):
        scanned = self.env["mailing.mailing"]._get_dynamic_field_names()
        self.assertIn("mailing_domain", self.env["mailing.mailing"]._fields)
        self.assertNotIn("mailing_domain", scanned)

    def test_the_rendered_fields_are_still_gated(self):
        scanned = self.env["mailing.mailing"]._get_dynamic_field_names()
        self.assertLessEqual(
            {"body_arch", "body_html", "email_from", "lang", "preview", "reply_to", "subject"},
            scanned,
        )
