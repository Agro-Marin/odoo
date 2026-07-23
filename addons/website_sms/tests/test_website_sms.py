# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteSms(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        Visitor = cls.env["website.visitor"]
        cls.partner_phone = Partner.create(
            {"name": "Reachable", "phone": "+52 55 1234 5678"}
        )
        cls.partner_no_phone = Partner.create({"name": "Unreachable"})
        # website.visitor.partner_id is computed from access_token: a non-32-char
        # token is interpreted as the linked partner id.
        cls.visitor_phone = Visitor.create({"access_token": str(cls.partner_phone.id)})
        cls.visitor_no_phone = Visitor.create(
            {"access_token": str(cls.partner_no_phone.id)}
        )

    def test_check_for_sms_composer_follows_partner_phone(self):
        """The SMS-composer check is true only when the partner has a phone."""
        self.assertTrue(self.visitor_phone._check_for_sms_composer())
        self.assertFalse(self.visitor_no_phone._check_for_sms_composer())

    def test_action_send_sms_without_phone_raises(self):
        """Sending an SMS to a visitor with no reachable phone is rejected."""
        with self.assertRaises(UserError):
            self.visitor_no_phone.action_send_sms()

    def test_action_send_sms_opens_composer_for_partner(self):
        """Sending an SMS opens the composer targeting the visitor's partner."""
        action = self.visitor_phone.action_send_sms()
        self.assertEqual(action["res_model"], "sms.composer")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_res_id"], self.partner_phone.id)
        self.assertEqual(action["context"]["default_number_field_name"], "phone")

    def test_prepare_sms_composer_context(self):
        """The composer context points at the partner's phone in comment mode."""
        ctx = self.visitor_phone._prepare_sms_composer_context()
        self.assertEqual(ctx["default_res_model"], "res.partner")
        self.assertEqual(ctx["default_res_id"], self.partner_phone.id)
        self.assertEqual(ctx["default_composition_mode"], "comment")
        self.assertEqual(ctx["default_number_field_name"], "phone")
