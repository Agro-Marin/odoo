from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("standard", "at_install")
class TestAccountCashRounding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref("base.USD")

        def rounding(method):
            return cls.env["account.cash.rounding"].create(
                {
                    "name": f"0.05 {method}",
                    "rounding": 0.05,
                    "strategy": "add_invoice_line",
                    "rounding_method": method,
                }
            )

        cls.half_up = rounding("HALF-UP")
        cls.up = rounding("UP")
        cls.down = rounding("DOWN")

    def test_round_half_up(self):
        self.assertEqual(self.half_up.round(1.02), 1.00)
        self.assertEqual(self.half_up.round(1.03), 1.05)
        self.assertEqual(self.half_up.round(1.025), 1.05)

    def test_round_up_down(self):
        self.assertEqual(self.up.round(1.02), 1.05)
        self.assertEqual(self.up.round(1.049), 1.05)
        self.assertEqual(self.down.round(1.03), 1.00)
        self.assertEqual(self.down.round(1.049), 1.00)

    def test_compute_difference_sign(self):
        self.assertAlmostEqual(
            self.half_up.compute_difference(self.currency, 1.02), -0.02
        )
        self.assertAlmostEqual(
            self.half_up.compute_difference(self.currency, 1.03), 0.02
        )
        self.assertAlmostEqual(self.up.compute_difference(self.currency, 1.02), 0.03)
        self.assertAlmostEqual(self.down.compute_difference(self.currency, 1.03), -0.03)

    def test_compute_difference_negative_amount(self):
        self.assertAlmostEqual(
            self.half_up.compute_difference(self.currency, -1.02), 0.02
        )

    def test_validate_rounding_must_be_positive(self):
        from odoo.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.env["account.cash.rounding"].create(
                {
                    "name": "bad",
                    "rounding": 0.0,
                    "strategy": "add_invoice_line",
                    "rounding_method": "HALF-UP",
                }
            )
