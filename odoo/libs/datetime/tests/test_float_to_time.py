import unittest
from datetime import time

from odoo.libs.datetime.date_utils import float_to_time


class TestFloatToTime(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(float_to_time(8.5), time(8, 30))
        self.assertEqual(float_to_time(12.25), time(12, 15))

    def test_minute_carry_does_not_crash(self):
        self.assertEqual(float_to_time(8.9999), time(9, 0))

    def test_carry_past_end_of_day(self):
        self.assertEqual(float_to_time(23.9999), time.max)

    def test_sentinel_24(self):
        self.assertEqual(float_to_time(24.0), time.max)

    def test_boundaries_accepted(self):
        self.assertEqual(float_to_time(0.0), time(0, 0))
        self.assertEqual(float_to_time(23.99), time(23, 59))


class TestOutOfDomain(unittest.TestCase):
    def test_negative(self):
        with self.assertRaises(ValueError) as ctx:
            float_to_time(-1.0)
        self.assertIn("[0.0, 24.0]", str(ctx.exception))

    def test_small_negative(self):
        with self.assertRaises(ValueError):
            float_to_time(-0.5)

    def test_above_24_no_longer_silently_clamped(self):
        for value in (24.5, 25.0, 100.0):
            with self.assertRaises(ValueError):
                float_to_time(value)

    def test_nan(self):
        with self.assertRaises(ValueError):
            float_to_time(float("nan"))

    def test_infinity(self):
        with self.assertRaises(ValueError):
            float_to_time(float("inf"))
        with self.assertRaises(ValueError):
            float_to_time(float("-inf"))


if __name__ == "__main__":
    unittest.main()
