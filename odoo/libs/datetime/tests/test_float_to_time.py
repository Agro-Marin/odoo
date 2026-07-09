"""Regression tests for ``odoo.libs.datetime.date_utils.float_to_time``."""

import unittest
from datetime import time

from odoo.libs.datetime.date_utils import float_to_time


class TestFloatToTime(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(float_to_time(8.5), time(8, 30))
        self.assertEqual(float_to_time(12.25), time(12, 15))

    def test_minute_carry_does_not_crash(self):
        # 60 * 0.9999 rounds to 60 minutes; must carry to the next hour, not
        # raise ValueError from time(h, 60).
        self.assertEqual(float_to_time(8.9999), time(9, 0))

    def test_carry_past_end_of_day(self):
        self.assertEqual(float_to_time(23.9999), time.max)

    def test_sentinel_24(self):
        self.assertEqual(float_to_time(24.0), time.max)


if __name__ == "__main__":
    unittest.main()
