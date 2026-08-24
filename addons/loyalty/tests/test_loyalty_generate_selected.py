from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyGenerateSelected(TransactionCase):
    """Coupon generation for explicitly selected customers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {"name": "Selected Program", "reward_ids": [(0, 0, {})]}
        )
        cls.partner_a = cls.env["res.partner"].create({"name": "Cust A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "Cust B"})

    def test_generate_selected_one_coupon_per_partner(self):
        """Selected mode issues one coupon per chosen customer."""
        wizard = self.env["loyalty.generate.wizard"].create(
            {
                "program_id": self.program.id,
                "mode": "selected",
                "customer_ids": [Command.set([self.partner_a.id, self.partner_b.id])],
                "points_granted": 5,
            }
        )
        self.assertEqual(wizard.coupon_qty, 2)
        coupons = wizard.generate_coupons()
        self.assertEqual(len(coupons), 2)
        self.assertEqual(coupons.mapped("partner_id"), self.partner_a + self.partner_b)

    def test_generate_zero_quantity_raises(self):
        """A zero-coupon batch is rejected before any card is created."""
        wizard = self.env["loyalty.generate.wizard"].create(
            {
                "program_id": self.program.id,
                "mode": "anonymous",
                "coupon_qty": 0,
                "points_granted": 5,
            }
        )

        with self.assertRaises(ValidationError):
            wizard.generate_coupons()

        self.assertFalse(
            self.env["loyalty.card"].search([("program_id", "=", self.program.id)])
        )
