"""Regression tests for ``odoo.libs.collections.frozen_dict.frozendict``.

``frozendict`` subclasses ``dict``, so every mutating entry point must be
overridden.  ``|=`` (``__ior__``) is easy to miss: the inherited
``dict.__ior__`` mutates in place and leaves the cached ``_hash`` stale.
"""

import copy
import pickle
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


class TestFrozendictCopyAndPickle(unittest.TestCase):
    """Being immutable must not mean being uncopyable.

    ``dict`` subclasses are reconstructed through the pickle protocol's
    "dictitems" slot, which replays the contents with ``obj[key] = value`` --
    straight into the ``__setitem__`` override, so all three of ``copy.copy``,
    ``copy.deepcopy`` and ``pickle`` raised ``NotImplementedError``.
    """

    def test_copy(self):
        fd = frozendict({"a": 1, "b": 2})
        clone = copy.copy(fd)
        self.assertIsInstance(clone, frozendict)
        self.assertEqual(dict(clone), {"a": 1, "b": 2})

    def test_deepcopy(self):
        fd = frozendict({"a": 1})
        clone = copy.deepcopy(fd)
        self.assertIsInstance(clone, frozendict)
        self.assertEqual(dict(clone), {"a": 1})

    def test_deepcopy_recurses_into_mutable_values(self):
        # frozendict is only shallowly immutable; a deep copy must not alias
        # the nested mutable value.
        fd = frozendict({"a": [1, 2]})
        clone = copy.deepcopy(fd)
        self.assertEqual(clone["a"], [1, 2])
        self.assertIsNot(clone["a"], fd["a"])
        clone["a"].append(3)
        self.assertEqual(fd["a"], [1, 2])

    def test_copy_shares_mutable_values(self):
        fd = frozendict({"a": [1, 2]})
        self.assertIs(copy.copy(fd)["a"], fd["a"])

    def test_pickle_roundtrip(self):
        fd = frozendict({"a": 1, "b": "two"})
        # S301 is suppressed below: this round-trips a value the test just
        # serialized itself, so there is no untrusted input anywhere near it.
        restored = pickle.loads(pickle.dumps(fd))  # noqa: S301
        self.assertIsInstance(restored, frozendict)
        self.assertEqual(dict(restored), {"a": 1, "b": "two"})

    def test_copy_is_still_immutable(self):
        clone = copy.deepcopy(frozendict({"a": 1}))
        with self.assertRaises(NotImplementedError):
            clone["b"] = 2

    def test_copy_preserves_hash(self):
        fd = frozendict({"a": 1, "b": 2})
        self.assertEqual(hash(copy.deepcopy(fd)), hash(fd))
        self.assertEqual(hash(pickle.loads(pickle.dumps(fd))), hash(fd))  # noqa: S301

    def test_nested_in_a_deepcopied_structure(self):
        # The realistic shape: something copies a container that happens to
        # hold a frozendict (e.g. an Environment context).
        payload = {"ctx": frozendict({"lang": "en_US"}), "other": [1]}
        clone = copy.deepcopy(payload)
        self.assertIsInstance(clone["ctx"], frozendict)
        self.assertEqual(clone["ctx"]["lang"], "en_US")


if __name__ == "__main__":
    unittest.main()
