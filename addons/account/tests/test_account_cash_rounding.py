from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("standard", "at_install")
class TestAccountCashRounding(TransactionCase):
    """Direct unit coverage for the pure ``account.cash.rounding`` math
    (``round`` / ``compute_difference``), which was previously only exercised
    indirectly through full-invoice integration tests.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref("base.USD")  # 0.01 precision

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
        self.assertEqual(self.half_up.round(1.02), 1.00)  # nearest coin below
        self.assertEqual(self.half_up.round(1.03), 1.05)  # nearest coin above
        self.assertEqual(self.half_up.round(1.025), 1.05)  # tie rounds up

    def test_round_up_down(self):
        # UP always climbs to the next coin, DOWN always drops to the previous one
        self.assertEqual(self.up.round(1.02), 1.05)
        self.assertEqual(self.up.round(1.049), 1.05)
        self.assertEqual(self.down.round(1.03), 1.00)
        self.assertEqual(self.down.round(1.049), 1.00)

    def test_compute_difference_sign(self):
        # Rounding down yields a negative difference, rounding up a positive one;
        # this sign convention is what the invoice rounding line depends on.
        self.assertAlmostEqual(
            self.half_up.compute_difference(self.currency, 1.02), -0.02
        )
        self.assertAlmostEqual(
            self.half_up.compute_difference(self.currency, 1.03), 0.02
        )
        self.assertAlmostEqual(self.up.compute_difference(self.currency, 1.02), 0.03)
        self.assertAlmostEqual(self.down.compute_difference(self.currency, 1.03), -0.03)

    def test_compute_difference_negative_amount(self):
        # A negative base amount must still produce a correctly-signed difference.
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
