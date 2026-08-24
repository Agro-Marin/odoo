from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUtmSourceModel(TransactionCase):
    """utm.source name auto-dedup, name generation and the referral guard."""

    @property
    def Source(self):
        return self.env["utm.source"]

    def test_create_deduplicates_name(self):
        """Creating two sources with the same name auto-uniquifies the second."""
        first = self.Source.create({"name": "LoopTestSource"})
        second = self.Source.create({"name": "LoopTestSource"})
        self.assertEqual(first.name, "LoopTestSource")
        self.assertNotEqual(second.name, "LoopTestSource")

    def test_generate_name_truncates_long_content(self):
        """Long content is truncated with an ellipsis in the generated name."""
        record = self.Source.create({"name": "Anchor"})
        name = self.Source._generate_name(record, "x" * 30)
        self.assertIn("...", name)

    def test_generate_name_empty_content_is_false(self):
        """Empty content yields no generated name (boundary)."""
        record = self.Source.create({"name": "Anchor2"})
        self.assertFalse(self.Source._generate_name(record, ""))

    def test_referral_source_cannot_be_deleted(self):
        """The reserved 'Referral' source is protected from deletion."""
        referral = self.env.ref("utm.utm_source_referral", raise_if_not_found=False)
        if not referral:
            self.skipTest("referral source not installed")
        with self.assertRaises(ValidationError):
            referral.unlink()
