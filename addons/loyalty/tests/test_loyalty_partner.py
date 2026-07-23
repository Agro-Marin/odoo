# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyPartner(TransactionCase):
    """res.partner active loyalty-card count and the cards smart action."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {"name": "Partner Program", "reward_ids": [(0, 0, {})]}
        )
        cls.partner = cls.env["res.partner"].create({"name": "Loyal Customer"})
        cls.card = cls.env["loyalty.card"].create(
            {"program_id": cls.program.id, "partner_id": cls.partner.id, "points": 50}
        )

    def test_active_card_count(self):
        """A partner with a positive-balance card counts one active card."""
        self.assertEqual(self.partner.loyalty_card_count, 1)

    def test_zero_balance_card_not_counted(self):
        """A zero-point card is not counted as active (boundary)."""
        partner = self.env["res.partner"].create({"name": "No Points"})
        self.env["loyalty.card"].create(
            {"program_id": self.program.id, "partner_id": partner.id, "points": 0}
        )
        self.assertEqual(partner.loyalty_card_count, 0)

    def test_action_view_loyalty_cards(self):
        """The smart action targets loyalty cards scoped to the partner."""
        action = self.partner.action_view_loyalty_cards()
        self.assertEqual(action["res_model"], "loyalty.card")
        self.assertIn(self.partner.id, action["domain"][0][2])
