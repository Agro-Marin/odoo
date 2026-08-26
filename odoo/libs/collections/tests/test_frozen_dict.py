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
        restored = pickle.loads(pickle.dumps(fd))
        self.assertIsInstance(restored, frozendict)
        self.assertEqual(dict(restored), {"a": 1, "b": "two"})

    def test_copy_is_still_immutable(self):
        clone = copy.deepcopy(frozendict({"a": 1}))
        with self.assertRaises(NotImplementedError):
            clone["b"] = 2

    def test_copy_preserves_hash(self):
        fd = frozendict({"a": 1, "b": 2})
        self.assertEqual(hash(copy.deepcopy(fd)), hash(fd))
        self.assertEqual(hash(pickle.loads(pickle.dumps(fd))), hash(fd))

    def test_nested_in_a_deepcopied_structure(self):
        payload = {"ctx": frozendict({"lang": "en_US"}), "other": [1]}
        clone = copy.deepcopy(payload)
        self.assertIsInstance(clone["ctx"], frozendict)
        self.assertEqual(clone["ctx"]["lang"], "en_US")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()


class TestFrozendictRejectsEveryMutator(unittest.TestCase):
    """Ported from `odoo/addons/base/tests/test_func.py`.

    `TestFrozendictImmutability` above already covers `__setitem__`,
    `update` and `|=`; these are the five mutators it did not, which the
    base copy did.
    """

    def setUp(self):
        self.frozen = frozendict({"name": "Joe", "age": 42})

    def test_delitem_rejected(self):
        with self.assertRaises(Exception):
            del self.frozen["name"]

    def test_setdefault_rejected(self):
        with self.assertRaises(Exception):
            self.frozen.setdefault("surname", "Jack")

    def test_pop_rejected(self):
        with self.assertRaises(Exception):
            self.frozen.pop("name", "Jack")
        with self.assertRaises(Exception):
            self.frozen.pop("surname", "Jack")

    def test_popitem_rejected(self):
        with self.assertRaises(Exception):
            self.frozen.popitem()

    def test_clear_rejected(self):
        with self.assertRaises(Exception):
            self.frozen.clear()


class TestFrozendictHashesNestedValues(unittest.TestCase):
    def test_hash_of_a_flat_mapping(self):
        hash(frozendict({"name": "Joe", "age": 42}))

    def test_hash_reaches_into_lists_and_tuples(self):
        """The base copy built this with `Command.create(...)`, which is a
        3-tuple; spelled literally here so the suite stays inside `odoo.libs`
        and does not reach into the ORM for a fixture shape."""
        hash(
            frozendict(
                {
                    "user_id": (42, "Joe"),
                    "line_ids": [(0, 0, {"values": [42]})],
                }
            )
        )
