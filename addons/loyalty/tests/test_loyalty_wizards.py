# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyWizards(TransactionCase):
    """Loyalty card balance-update and coupon-generation wizards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {"name": "Wizard Program", "reward_ids": [(0, 0, {})]}
        )
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})
        cls.card = cls.env["loyalty.card"].create(
            {"program_id": cls.program.id, "partner_id": cls.partner.id, "points": 50}
        )

    def test_update_balance_issues_points_and_logs_history(self):
        """Raising the balance updates the card and logs the issued points."""
        wizard = self.env["loyalty.card.update.balance"].create(
            {"card_id": self.card.id, "new_balance": 80.0, "description": "Bonus"}
        )
        wizard.action_update_card_point()
        self.assertEqual(self.card.points, 80.0)
        self.assertTrue(
            self.env["loyalty.history"].search(
                [("card_id", "=", self.card.id), ("issued", ">", 0)]
            )
        )

    def test_update_balance_rejects_same_or_negative(self):
        """An unchanged or negative balance is rejected."""
        wizard = self.env["loyalty.card.update.balance"].create(
            {"card_id": self.card.id, "new_balance": 50.0, "description": "noop"}
        )
        with self.assertRaises(ValidationError):
            wizard.action_update_card_point()

    def test_generate_anonymous_coupons(self):
        """Generating anonymous coupons creates the requested quantity."""
        wizard = self.env["loyalty.generate.wizard"].create(
            {
                "program_id": self.program.id,
                "mode": "anonymous",
                "coupon_qty": 3,
                "points_granted": 10,
            }
        )
        coupons = wizard.generate_coupons()
        self.assertEqual(len(coupons), 3)
        self.assertTrue(all(coupon.points == 10 for coupon in coupons))

    def test_generate_requires_positive_quantity(self):
        """Generating with a non-positive quantity is rejected."""
        wizard = self.env["loyalty.generate.wizard"].create(
            {
                "program_id": self.program.id,
                "mode": "anonymous",
                "coupon_qty": 0,
                "points_granted": 10,
            }
        )
        with self.assertRaises(ValidationError):
            wizard.generate_coupons()
