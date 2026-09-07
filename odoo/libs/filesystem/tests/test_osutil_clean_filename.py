import unittest

from odoo.libs.filesystem.osutil import clean_filename


class TestCleanFilename(unittest.TestCase):
    def test_plain_names_pass_through(self):
        self.assertEqual(clean_filename("report.pdf"), "report.pdf")
        self.assertEqual(
            clean_filename("My Invoice (2024).xlsx"), "My Invoice (2024).xlsx"
        )

    def test_reserved_name_rejected(self):
        for name in ("CON", "con.txt", "NUL", "COM1", "LPT9.log"):
            self.assertEqual(clean_filename(name), "Untitled", name)

    def test_reserved_name_masked_by_leading_dot_or_hyphen_is_still_rejected(self):
        for name in ("-CON", ".CON", "--CON.txt", "...NUL"):
            self.assertEqual(clean_filename(name), "Untitled", name)

    def test_empty_or_fully_stripped_name_falls_back_to_untitled(self):
        self.assertEqual(clean_filename(""), "Untitled")
        self.assertEqual(clean_filename("..."), "Untitled")
        self.assertEqual(clean_filename("***"), "Untitled")

    def test_disallowed_characters_are_replaced(self):
        self.assertEqual(
            clean_filename("a/b\\c*d?.txt", replacement="_"), "a_b_c_d_.txt"
        )


if __name__ == "__main__":
    unittest.main()
