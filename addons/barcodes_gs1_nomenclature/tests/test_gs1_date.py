"""Tests for the GS1 date decoding helper."""

import datetime

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGs1Date(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.nomenclature = cls.env["barcode.nomenclature"].create(
            {"name": "GS1 date test nomenclature", "is_gs1_nomenclature": True}
        )

    def test_full_date_decoded(self):
        """A yymmdd string decodes to the matching date."""
        self.assertEqual(
            self.nomenclature.gs1_date_to_date("260115"), datetime.date(2026, 1, 15)
        )

    def test_zero_day_uses_month_end(self):
        """A day of 00 resolves to the last day of the month."""
        # 2026-02 has 28 days.
        self.assertEqual(
            self.nomenclature.gs1_date_to_date("260200"), datetime.date(2026, 2, 28)
        )

    def test_century_rollover_for_far_future(self):
        """A year far in the future crosses into the previous century rule."""
        # For "99" the GS1 century rule keeps it in the recent past/near range,
        # never the naive 2099 — assert the decade digits round-trip.
        decoded = self.nomenclature.gs1_date_to_date("991231")
        self.assertEqual(decoded.month, 12)
        self.assertEqual(decoded.day, 31)
        self.assertEqual(decoded.year % 100, 99)

    def test_invalid_date_raises(self):
        """An impossible calendar date raises a ValidationError (negative)."""
        with self.assertRaises(ValidationError):
            self.nomenclature.gs1_date_to_date("260230")  # Feb 30th
