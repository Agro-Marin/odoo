"""Regression tests for ``odoo.libs.collections.frozen_dict.frozendict``.

``frozendict`` subclasses ``dict``, so every mutating entry point must be
overridden.  ``|=`` (``__ior__``) is easy to miss: the inherited
``dict.__ior__`` mutates in place and leaves the cached ``_hash`` stale.
"""

import unittest

from odoo.libs.collections.frozen_dict import frozendict


class TestFrozendictImmutability(unittest.TestCase):
    def test_ior_rejected(self):
        fd = frozendict({"a": 1})
        with self.assertRaises(NotImplementedError):
            fd |= {"b": 2}
        self.assertEqual(dict(fd), {"a": 1})

    def test_ior_does_not_stale_cached_hash(self):
        fd = frozendict({"a": 1})
        h = hash(fd)
        with self.assertRaises(NotImplementedError):
            fd |= {"b": 2}
        self.assertEqual(hash(fd), h)

    def test_setitem_rejected(self):
        fd = frozendict({"a": 1})
        with self.assertRaises(NotImplementedError):
            fd["b"] = 2

    def test_update_rejected(self):
        fd = frozendict({"a": 1})
        with self.assertRaises(NotImplementedError):
            fd.update({"b": 2})


if __name__ == "__main__":
    unittest.main()
