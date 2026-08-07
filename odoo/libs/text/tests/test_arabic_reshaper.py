import unittest

from odoo.libs.text.arabic_reshaper import reshape

ZWJ = "‍"


class TestArabicReshaper(unittest.TestCase):
    def test_zwj_before_ligature_does_not_crash(self):
        for text in (f"لا{ZWJ}لا", f"ل{ZWJ}لا", f"بلا{ZWJ}لا"):
            self.assertIsInstance(reshape(text), str)

    def test_plain_text_still_reshapes(self):
        out = reshape("السلام")
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_empty(self):
        self.assertEqual(reshape(""), "")


if __name__ == "__main__":
    unittest.main()
