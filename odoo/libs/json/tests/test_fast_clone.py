import unittest
from typing import Any

from odoo_rust import fast_clone as _fast_clone


def fast_clone(obj: Any) -> Any:
    return _fast_clone(obj)


class TestFastCloneSemantics(unittest.TestCase):
    def test_equal_but_independent(self):
        src: Any = {"a": 1, "b": [1, 2, {"c": 3}], "t": (4, 5), "s": "x", "n": None}
        dst = fast_clone(src)
        self.assertEqual(dst, src)
        self.assertIsNot(dst, src)
        self.assertIsNot(dst["b"], src["b"])
        self.assertIsNot(dst["b"][2], src["b"][2])

    def test_mutating_the_clone_does_not_touch_the_original(self):
        src: Any = {"list": [1, 2], "dict": {"k": "v"}}
        dst = fast_clone(src)
        dst["list"].append(3)
        dst["dict"]["k"] = "changed"
        self.assertEqual(src["list"], [1, 2])
        self.assertEqual(src["dict"]["k"], "v")

    def test_scalars_and_empty_containers(self):
        value: Any
        for value in (0, "", None, True, [], {}, (), {"x": []}, [{}]):
            self.assertEqual(fast_clone(value), value)

    def test_nested_lists_and_tuples(self):
        src: Any = [(1, [2, {"a": (3, 4)}]), {"b": [5]}]
        dst = fast_clone(src)
        self.assertEqual(dst, src)
        self.assertIsNot(dst[0][1], src[0][1])


class TestFastCloneSharingBoundary(unittest.TestCase):
    """What the clone rebuilds and what it deliberately shares.

    `Json.convert_to_record` clones so the record can be handed a value it may
    mutate without reaching the field cache. Anything the clone hands back by
    identity therefore defeats its own purpose, and these pin exactly where
    that line falls.
    """

    def test_a_dict_subclass_is_rebuilt_not_aliased(self):
        """Dispatching on `PyDict_CheckExact` made a subclass a *leaf*.

        It fell through every container branch to the share-by-reference tail,
        so the "clone" returned the caller's own object — the cached value
        itself — and every mutation of the "copy" landed in the cache.
        """

        class Subclass(dict):
            pass

        inner = {"k": 1}
        src = Subclass(a=inner)
        dst = fast_clone(src)
        self.assertIsNot(dst, src)
        self.assertIsNot(dst["a"], inner)
        self.assertEqual(dst, {"a": {"k": 1}})
        dst["a"]["k"] = 2
        self.assertEqual(inner["k"], 1)

    def test_a_list_subclass_is_rebuilt_not_aliased(self):
        class Subclass(list):
            pass

        inner: Any = {"k": 1}
        src = Subclass([inner])
        dst = fast_clone(src)
        self.assertIsNot(dst, src)
        self.assertIsNot(dst[0], inner)

    def test_a_tuple_subclass_is_rebuilt_not_aliased(self):
        """Immutable itself, but its elements are not."""

        class Subclass(tuple):
            __slots__ = ()

        inner: Any = {"k": 1}
        src = Subclass([inner])
        dst = fast_clone(src)
        self.assertIsNot(dst[0], inner)

    def test_container_subclasses_normalize_to_the_builtin_type(self):
        """Type fidelity is not what the callers buy; isolation is.

        Preserving the exact class would mean calling its constructor from
        Rust, which every caller would pay for and none needs.
        """

        class Subclass(dict):
            pass

        self.assertIs(type(fast_clone(Subclass(a=1))), dict)

    def test_a_mutable_non_container_leaf_is_shared(self):
        """A documented boundary, pinned so it cannot move unnoticed.

        `set`/`bytearray` are not dict/list/tuple, so they take the leaf path
        and are shared. Neither can reach this function in practice — JSON and
        Properties values round-trip through orjson first — but a caller that
        finds a way must know it does not get a copy.
        """
        shared: Any = {1, 2}
        src: Any = {"s": shared}
        self.assertIs(fast_clone(src)["s"], shared)


class TestFastCloneRecursionGuard(unittest.TestCase):
    def test_a_self_referential_dict_raises_instead_of_segfaulting(self):
        cyclic: dict = {}
        cyclic["self"] = cyclic
        with self.assertRaises(RecursionError):
            fast_clone(cyclic)

    def test_a_cyclic_list_raises(self):
        cyclic: list = []
        cyclic.append(cyclic)
        with self.assertRaises(RecursionError):
            fast_clone(cyclic)

    def test_legitimately_deep_nesting_still_clones(self):
        deep: dict = {}
        cur = deep
        for _ in range(100):
            cur["n"] = {}
            cur = cur["n"]
        clone = fast_clone(deep)
        self.assertIsNot(clone, deep)
        self.assertEqual(clone, deep)

    def test_pathologically_deep_nesting_raises(self):
        deep: dict = {}
        cur = deep
        for _ in range(600):
            cur["n"] = {}
            cur = cur["n"]
        with self.assertRaises(RecursionError):
            fast_clone(deep)


if __name__ == "__main__":
    unittest.main()
