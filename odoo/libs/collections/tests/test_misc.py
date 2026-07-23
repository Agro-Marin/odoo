"""Regression tests for ``odoo.libs.collections.misc.Collector``."""

import unittest

from odoo.libs.collections.misc import Collector


class TestCollector(unittest.TestCase):
    def test_discard_accepts_generator(self):
        # ``excludes`` is scanned twice; a generator would be exhausted after the
        # first pass and silently remove nothing on the second.
        c = Collector()
        c["a"] = (1, 2)
        c["b"] = (3,)
        c.discard_keys_and_values(x for x in (1, 3))
        self.assertEqual(c["a"], (2,))
        self.assertEqual(c["b"], ())

    def test_discard_removes_keys_and_values(self):
        # excludes are dropped both as keys and as values wherever they occur.
        c = Collector()
        c["a"] = (1, 2)
        c["k"] = (2, 3)
        c.discard_keys_and_values(["a", 2])
        self.assertNotIn("a", c)
        self.assertEqual(c["k"], (3,))


if __name__ == "__main__":
    unittest.main()
