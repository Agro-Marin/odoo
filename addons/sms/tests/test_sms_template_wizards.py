from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSmsTemplateWizards(TransactionCase):
    """sms.template copy, template preview rendering and sender-name validation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env["ir.model"]._get("res.partner")
        cls.template = cls.env["sms.template"].create(
            {"name": "Greeting", "model_id": cls.model.id, "body": "Hello"}
        )
        cls.partner = cls.env["res.partner"].create({"name": "Alice"})

    def test_template_copy_appends_copy(self):
        """Copying a template appends "(copy)" to its name."""
        copy = self.template.copy()
        self.assertIn("(copy)", str(copy.name))

    def test_preview_renders_body_for_record(self):
        """The preview renders the template body against a chosen record."""
        preview = self.env["sms.template.preview"].create(
            {
                "sms_template_id": self.template.id,
                "resource_ref": f"res.partner,{self.partner.id}",
            }
        )
        self.assertEqual(preview.body, "Hello")
        self.assertFalse(preview.no_record)

    def test_sender_name_invalid_characters_raises(self):
        """A sender name shorter than the allowed pattern raises ValidationError."""
        account = self.env["iap.account"].get("sms")

        with self.assertRaises(ValidationError):
            self.env["sms.account.sender"].create(
                {"account_id": account.id, "sender_name": "a!"}
            )

    def test_sender_name_valid_prefix_with_trailing_garbage_raises(self):
        """A valid 3-char prefix followed by invalid trailing content must
        still raise -- the pattern is anchored end-to-end, not just at the
        start."""
        account = self.env["iap.account"].get("sms")

        with self.assertRaises(ValidationError):
            self.env["sms.account.sender"].create(
                {
                    "account_id": account.id,
                    "sender_name": "abc!!!lots-of-junk",
                }
            )

    def test_sender_name_too_long_raises(self):
        """A name over 11 valid characters has no upper bound to fall back
        on and must raise."""
        account = self.env["iap.account"].get("sms")

        with self.assertRaises(ValidationError):
            self.env["sms.account.sender"].create(
                {
                    "account_id": account.id,
                    "sender_name": "abcdefghijklmnop",
                }
            )

    def test_sender_name_valid_accepted(self):
        """A name within the allowed shape does not raise."""
        account = self.env["iap.account"].get("sms")

        sender = self.env["sms.account.sender"].create(
            {"account_id": account.id, "sender_name": "AgroMarin"}
        )
        self.assertEqual(sender.sender_name, "AgroMarin")
