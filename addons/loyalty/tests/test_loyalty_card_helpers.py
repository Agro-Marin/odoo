"""Tests for the loyalty-card helper methods."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyCardHelpers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {
                "name": "LC helper program",
                "program_type": "loyalty",
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "LC helper partner"})

    def _card(self, points=0.0, code="LCHELPER0001"):
        return self.env["loyalty.card"].create(
            {
                "program_id": self.program.id,
                "partner_id": self.partner.id,
                "points": points,
                "code": code,
            }
        )

    def test_generate_code_is_nonempty_string(self):
        """The default code generator yields a non-empty string."""
        code = self.env["loyalty.card"]._generate_code()
        self.assertIsInstance(code, str)
        self.assertTrue(code)

    def test_format_points_includes_amount_and_label(self):
        """Point formatting embeds the amount and the program's point label."""
        card = self._card(points=12.0)
        formatted = card._format_points(12.0)
        self.assertIn("12", formatted)
        self.assertIn(card.program_id.portal_point_name, formatted)

    def test_display_name_includes_code(self):
        """The card display name carries its code."""
        card = self._card(code="LCHELPER-XYZ")
        card.invalidate_recordset(["display_name"])
        self.assertIn("LCHELPER-XYZ", card.display_name)
