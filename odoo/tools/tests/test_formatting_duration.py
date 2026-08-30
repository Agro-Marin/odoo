import unittest

from odoo.tools.formatting import format_duration


class TestFormatDuration(unittest.TestCase):
    def test_a_negative_that_rounds_to_nothing_has_no_sign(self):
        # The sign was taken from the input, after the magnitude had already
        # rounded away, so anything under half a minute printed "-00:00".
        for value in (-0.001, -0.004, -0.008):
            with self.subTest(value=value):
                self.assertEqual(format_duration(value), "00:00")

    def test_a_negative_that_survives_rounding_keeps_its_sign(self):
        self.assertEqual(format_duration(-1.5), "-01:30")
        self.assertEqual(format_duration(-0.02), "-00:01")

    def test_positives_are_unchanged(self):
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(1.5), "01:30")
        self.assertEqual(format_duration(0.999), "01:00")


if __name__ == "__main__":
    unittest.main()
