import unittest

from odoo.tools.security import consteq


class TestConsteq(unittest.TestCase):
    def test_equal_strings(self):
        self.assertTrue(consteq("a1b2c3", "a1b2c3"))
        self.assertTrue(consteq(b"a1b2c3", "a1b2c3"))

    def test_different_strings(self):
        self.assertFalse(consteq("a1b2c3", "a1b2c4"))
        self.assertFalse(consteq("a1b2c3", "a1b2c3d"))

    def test_non_ascii_client_input_is_a_mismatch(self):
        self.assertFalse(consteq("é" * 22, "A" * 22))
        self.assertFalse(consteq("A" * 22, "éè"))
        self.assertTrue(consteq("é", "é"))

    def test_a_missing_value_is_a_mismatch(self):
        self.assertFalse(consteq(None, "abc"))
        self.assertFalse(consteq("abc", False))
        self.assertFalse(consteq(None, None))
