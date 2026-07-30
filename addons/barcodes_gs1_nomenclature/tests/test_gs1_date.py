"""Tests for the GS1 date decoding helper."""

import datetime

from freezegun import freeze_time

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

    @freeze_time("2026-06-15")
    def test_century_rollover_for_far_future(self):
        """A two-digit 99 decodes to the previous century, not the naive 2099."""
        # GS1 7.12: 99 - 26 = 73, inside the 51..99 window, so the century is
        # the current one minus 1. The date is frozen because the rule reads
        # today's year — asserting year % 100 would also pass on 2099, which is
        # the reading this test exists to rule out.
        self.assertEqual(
            self.nomenclature.gs1_date_to_date("991231"), datetime.date(1999, 12, 31)
        )

    def test_invalid_date_raises(self):
        """An impossible calendar date raises a ValidationError (negative)."""
        with self.assertRaises(ValidationError):
            self.nomenclature.gs1_date_to_date("260230")  # Feb 30th
