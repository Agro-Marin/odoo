from odoo.tests.common import TransactionCase


class TestAmountToTextBackend(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref("base.USD")

    def test_negative_fractional_amount(self):
        result = self.usd.amount_to_text(-0.50)
        self.assertIn("Minus", result, f"Negative sign lost in: {result}")

    def test_negative_one_dollar(self):
        result = self.usd.amount_to_text(-1.50)
        self.assertIn("Minus", result, f"Negative sign lost in: {result}")
        self.assertIn("Fifty", result, f"Fractional part wrong in: {result}")

    def test_positive_amount_unchanged(self):
        result = self.usd.amount_to_text(1.50)
        self.assertNotIn("Minus", result)
        self.assertIn("One", result)
        self.assertIn("Fifty", result)

    def test_zero_amount(self):
        result = self.usd.amount_to_text(0.0)
        self.assertNotIn("Minus", result)
