import unittest

from odoo.orm.components.compute import ComputeEngine


class TestComputeScheduling(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ComputeEngine()

    def test_initially_empty(self) -> None:
        self.assertFalse(self.engine.has_pending())
        self.assertEqual(list(self.engine.pending_fields()), [])

    def test_schedule(self) -> None:
        self.engine.schedule("total", [1, 2, 3])
        self.assertTrue(self.engine.has_pending())
        self.assertTrue(self.engine.is_pending("total", 1))
        self.assertFalse(self.engine.is_pending("total", 99))

    def test_schedule_idempotent(self) -> None:
        self.engine.schedule("total", [1, 2])
        self.engine.schedule("total", [2, 3])
        ids = self.engine.pending_ids("total")
        self.assertEqual(set(ids), {1, 2, 3})

    def test_mark_done(self) -> None:
        self.engine.schedule("total", [1, 2, 3])
        self.engine.mark_done("total", [1, 2])
        self.assertFalse(self.engine.is_pending("total", 1))
        self.assertTrue(self.engine.is_pending("total", 3))

    def test_mark_done_removes_empty_field(self) -> None:
        self.engine.schedule("total", [1])
        self.engine.mark_done("total", [1])
        self.assertFalse(self.engine.has_pending())
        self.assertNotIn("total", self.engine._pending)

    def test_mark_done_nonexistent(self) -> None:
        self.engine.mark_done("total", [1, 2])

    def test_pending_fields(self) -> None:
        self.engine.schedule("total", [1])
        self.engine.schedule("tax", [2])
        fields = set(self.engine.pending_fields())
        self.assertEqual(fields, {"total", "tax"})

    def test_pending_ids_empty(self) -> None:
        ids = self.engine.pending_ids("nonexistent")
        self.assertEqual(len(ids), 0)

    def test_pending_real_fields(self) -> None:
        self.engine.schedule("total", [0])
        self.engine.schedule("tax", [1])
        real = self.engine.pending_real_fields()
        self.assertEqual(real, ["tax"])

    def test_pending_real_fields_mixed(self) -> None:
        self.engine.schedule("total", [0, 1])
        real = self.engine.pending_real_fields()
        self.assertEqual(real, ["total"])

    def test_schedule_empty_creates_no_phantom(self) -> None:
        self.engine.schedule("total", [])
        self.assertFalse(self.engine.has_pending())
        self.assertFalse(self.engine.has_pending_field("total"))
        self.engine.schedule("tax", (i for i in [] if i))
        self.assertNotIn("tax", self.engine._pending)
        self.assertEqual(self.engine.pending_real_fields(), [])

    def test_schedule_preserves_factory_ordering(self) -> None:
        from odoo.libs.collections import OrderedSet

        engine = ComputeEngine(pending_factory=OrderedSet)
        engine.schedule("total", [3, 1, 2])
        self.assertIsInstance(engine._pending["total"], OrderedSet)
        self.assertEqual(list(engine._pending["total"]), [3, 1, 2])

    def test_has_pending_field(self) -> None:
        self.assertFalse(self.engine.has_pending_field("total"))
        self.engine.schedule("total", [1])
        self.assertTrue(self.engine.has_pending_field("total"))
        self.assertFalse(self.engine.has_pending_field("tax"))

    def test_has_pending_field_empty_set(self) -> None:
        self.engine.schedule("total", [1])
        self.engine.mark_done("total", [1])
        self.assertFalse(self.engine.has_pending_field("total"))

    def test_discard_field(self) -> None:
        self.engine.schedule("total", [1, 2])
        self.engine.schedule("tax", [3])
        self.engine.discard_field("total")
        self.assertFalse(self.engine.has_pending_field("total"))
        self.assertTrue(self.engine.has_pending_field("tax"))

    def test_discard_field_missing(self) -> None:
        self.engine.discard_field("nonexistent")

    def test_clear(self) -> None:
        self.engine.schedule("total", [1, 2])
        self.engine.schedule("tax", [3])
        self.engine.clear()
        self.assertFalse(self.engine.has_pending())


class TestComputeProtection(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ComputeEngine()

    def test_initially_not_protected(self) -> None:
        self.assertFalse(self.engine.is_protected("total", 1))
        self.assertEqual(self.engine.protected_ids("total"), frozenset())

    def test_protect(self) -> None:
        self.engine.push_protection()
        self.engine.protect("total", frozenset([1, 2]))
        self.assertTrue(self.engine.is_protected("total", 1))
        self.assertFalse(self.engine.is_protected("total", 3))

    def test_nested_protection(self) -> None:
        self.engine.push_protection()
        self.engine.protect("total", frozenset([1]))
        self.engine.push_protection()
        self.engine.protect("total", frozenset([2]))
        self.assertTrue(self.engine.is_protected("total", 1))
        self.assertTrue(self.engine.is_protected("total", 2))
        self.engine.pop_protection()
        self.assertTrue(self.engine.is_protected("total", 1))
        self.assertFalse(self.engine.is_protected("total", 2))

    def test_protect_merges_in_same_scope(self) -> None:
        self.engine.push_protection()
        self.engine.protect("total", frozenset([1]))
        self.engine.protect("total", frozenset([2]))
        self.assertTrue(self.engine.is_protected("total", 1))
        self.assertTrue(self.engine.is_protected("total", 2))

    def test_pop_returns_scope(self) -> None:
        self.engine.push_protection()
        self.engine.protect("total", frozenset([1]))
        scope = self.engine.pop_protection()
        self.assertIn("total", scope)

    def test_protected_ids(self) -> None:
        self.engine.push_protection()
        self.engine.protect("total", frozenset([1, 2]))
        ids = self.engine.protected_ids("total")
        self.assertEqual(ids, frozenset([1, 2]))


class TestComputeEngineRepr(unittest.TestCase):
    def test_repr_empty(self) -> None:
        engine = ComputeEngine()
        r = repr(engine)
        self.assertIn("pending=0", r)
        self.assertIn("scopes=0", r)

    def test_repr_with_data(self) -> None:
        engine = ComputeEngine()
        engine.schedule("total", [1, 2])
        engine.push_protection()
        r = repr(engine)
        self.assertIn("pending=1f/2e", r)
        self.assertIn("scopes=1", r)


class TestComputeCustomFactory(unittest.TestCase):
    def test_custom_factory(self) -> None:
        class OrderedSet(set):
            pass

        engine = ComputeEngine(pending_factory=OrderedSet)
        engine.schedule("total", [1, 2])
        pending = engine._pending["total"]
        self.assertIsInstance(pending, OrderedSet)


if __name__ == "__main__":
    unittest.main()
