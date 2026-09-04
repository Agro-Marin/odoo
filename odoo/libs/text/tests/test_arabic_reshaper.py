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

    def test_distinct_ligatures_pick_their_own_form(self):
        # LIGATURES_RE has one alternative per ligature; each match must
        # select its own row of GROUP_INDEX_TO_LIGATURE_FORMs, not always
        # the last one (a regression this class used to have when the
        # regex had no capturing groups at all).
        self.assertEqual(reshape("لا"), "ﻻ")
        self.assertEqual(reshape("الله"), "ﷲ")
        self.assertNotEqual(reshape("لا"), reshape("الله"))


if __name__ == "__main__":
    unittest.main()
