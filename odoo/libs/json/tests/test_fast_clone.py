"""Correctness and safety of the Rust ``fast_clone``.

``fast_clone`` had no correctness test despite being load-bearing in
``Json.convert_to_record`` and several ``Properties`` paths, whose values come
from addon-writable data. These pin both halves:

* **Deep-copy semantics** — the result equals the input but shares no mutable
  container, so mutating the clone cannot reach back into the original (the whole
  reason the ORM clones cached JSON before handing it out).
* **The recursion guard** — a *cyclic* structure (no memo to break the loop) and
  a pathologically deep one must raise ``RecursionError``, not overflow the
  native stack and segfault. Before the guard, either input crashed the
  interpreter outright.

Imports ``odoo_rust`` directly (a standalone compiled extension); no ORM.
"""

import unittest
from typing import Any

from odoo_rust import fast_clone as _fast_clone


def fast_clone(obj: Any) -> Any:
    """Typed shim: the Rust ``fast_clone`` returns ``PyAny`` (mypy ``object``),
    which is not indexable; the tests below index into cloned containers."""
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
        # ~100 levels — far more than any real Properties/JSON blob, well under
        # the cap, so it must succeed.
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
        for _ in range(600):  # over the cap
            cur["n"] = {}
            cur = cur["n"]
        with self.assertRaises(RecursionError):
            fast_clone(deep)


if __name__ == "__main__":
    unittest.main()
