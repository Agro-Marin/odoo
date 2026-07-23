"""Pure-Python tests for FieldCache — no Odoo, no database required.

Uses plain strings as mock "field" keys to prove the cache is fully
decoupled from the ORM runtime.
"""

import unittest

from odoo.orm.components.cache import FieldCache


class TestFieldCacheData(unittest.TestCase):
    """Test basic data access: get, set, has, batch operations."""

    def setUp(self) -> None:
        self.cache = FieldCache()

    def test_set_and_get(self) -> None:
        self.cache.set_value("name", 1, "Alice")
        self.assertEqual(self.cache.get_value("name", 1), "Alice")

    def test_get_missing_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.cache.get_value("name", 999)

    def test_get_missing_with_default(self) -> None:
        result = self.cache.get_value("name", 999, default=None)
        self.assertIsNone(result)

    def test_get_missing_does_not_vivify(self) -> None:
        """A get_value miss must not leave an empty {} entry in _data.

        Regression: indexing the defaultdict (``self._data[field]``) auto-created
        an empty sub-dict for any never-cached field on every miss, leaking
        entries that later inflate iter_field_items / invalidate_all scans.
        """
        # miss with a default
        self.cache.get_value("ghost", 1, default=None)
        self.assertNotIn("ghost", dict(self.cache.iter_field_items()))
        # miss that raises
        with self.assertRaises(KeyError):
            self.cache.get_value("ghost2", 1)
        self.assertNotIn("ghost2", dict(self.cache.iter_field_items()))

    def test_get_none_value_is_not_missing(self) -> None:
        self.cache.set_value("name", 1, None)
        self.assertIsNone(self.cache.get_value("name", 1))
        self.assertTrue(self.cache.has_value("name", 1))

    def test_has_value(self) -> None:
        self.assertFalse(self.cache.has_value("name", 1))
        self.cache.set_value("name", 1, "Alice")
        self.assertTrue(self.cache.has_value("name", 1))

    def test_has_value_wrong_field(self) -> None:
        self.cache.set_value("name", 1, "Alice")
        self.assertFalse(self.cache.has_value("email", 1))

    def test_get_field_data_creates_dict(self) -> None:
        d = self.cache.get_field_data("name")
        self.assertIsInstance(d, dict)
        self.assertEqual(len(d), 0)
        # mutating the returned dict is visible to the cache
        d[1] = "Bob"
        self.assertEqual(self.cache.get_value("name", 1), "Bob")

    def test_get_field_data_or_none(self) -> None:
        self.assertIsNone(self.cache.get_field_data_or_none("name"))
        self.cache.set_value("name", 1, "Alice")
        self.assertIsNotNone(self.cache.get_field_data_or_none("name"))



class TestFieldCacheDirty(unittest.TestCase):
    """Test dirty tracking."""

    def setUp(self) -> None:
        self.cache = FieldCache()

    def test_initially_not_dirty(self) -> None:
        self.assertFalse(self.cache.is_any_dirty())
        self.assertIsNone(self.cache.get_dirty("name"))

    def test_mark_dirty(self) -> None:
        self.cache.mark_dirty("name", [1, 2])
        self.assertTrue(self.cache.is_any_dirty())
        self.assertEqual(self.cache.get_dirty("name"), {1, 2})

    def test_mark_dirty_idempotent(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.mark_dirty("name", [1])
        self.assertEqual(len(self.cache.get_dirty("name")), 1)

    def test_mark_dirty_empty_creates_no_phantom(self) -> None:
        """mark_dirty() with empty ids must not vivify a phantom dirty field.

        Regression: ``self._dirty[field].update(ids)`` auto-created an empty set
        under *field*, so ``is_any_dirty``/``iter_dirty_fields`` (and hence
        ``UnitOfWork.dirty_models``) reported a field with nothing to flush.
        The real-world trigger is the all-NewId generator at textual.py.
        """
        self.cache.mark_dirty("name", [])
        self.assertFalse(self.cache.is_any_dirty())
        self.assertNotIn("name", list(self.cache.iter_dirty_fields()))
        # empty generator (all NewIds filtered out)
        self.cache.mark_dirty("ref", (i for i in [] if i))
        self.assertFalse(self.cache.is_any_dirty())
        self.assertEqual(self.cache.dirty_entry_count(), 0)

    def test_mark_dirty_empty_keeps_existing(self) -> None:
        """An empty mark on an already-dirty field leaves it untouched."""
        self.cache.mark_dirty("name", [1, 2])
        self.cache.mark_dirty("name", [])
        self.assertEqual(self.cache.get_dirty("name"), {1, 2})

    def test_has_dirty_field(self) -> None:
        self.assertFalse(self.cache.has_dirty_field("name"))
        self.cache.mark_dirty("name", [1])
        self.assertTrue(self.cache.has_dirty_field("name"))
        self.assertFalse(self.cache.has_dirty_field("email"))

    def test_pop_dirty(self) -> None:
        self.cache.mark_dirty("name", [1, 2])
        ids = self.cache.pop_dirty("name")
        self.assertEqual(ids, {1, 2})
        # after pop, field is no longer dirty
        self.assertIsNone(self.cache.get_dirty("name"))
        self.assertFalse(self.cache.is_any_dirty())

    def test_pop_dirty_missing(self) -> None:
        self.assertIsNone(self.cache.pop_dirty("name"))

    def test_iter_dirty_fields(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.mark_dirty("email", [2, 3])
        fields = set(self.cache.iter_dirty_fields())
        self.assertEqual(fields, {"name", "email"})

    def test_iter_dirty_fields_empty(self) -> None:
        self.assertEqual(list(self.cache.iter_dirty_fields()), [])

    def test_dirty_entry_count(self) -> None:
        self.assertEqual(self.cache.dirty_entry_count(), 0)
        self.cache.mark_dirty("name", [1, 2])
        self.cache.mark_dirty("email", [3])
        self.assertEqual(self.cache.dirty_entry_count(), 3)

    def test_dirty_entry_count_after_pop(self) -> None:
        self.cache.mark_dirty("name", [1, 2])
        self.cache.mark_dirty("email", [3])
        self.cache.pop_dirty("name")
        self.assertEqual(self.cache.dirty_entry_count(), 1)

    def test_custom_dirty_factory(self) -> None:
        # OrderedSet-like types (any MutableSet with .update()) are typical
        class OrderedSet(set):
            """Minimal ordered set stand-in for testing."""

        cache = FieldCache(dirty_factory=OrderedSet)
        cache.mark_dirty("name", [1, 2])
        dirty = cache.get_dirty("name")
        self.assertIsInstance(dirty, OrderedSet)
        self.assertEqual(dirty, {1, 2})


class TestFieldCachePatches(unittest.TestCase):
    """Test deferred x2many patches."""

    def setUp(self) -> None:
        self.cache = FieldCache()

    def test_no_patches(self) -> None:
        self.assertIsNone(self.cache.get_patches("line_ids"))

    def test_add_and_get_patch(self) -> None:
        self.cache.add_patch("line_ids", 1, 100)
        self.cache.add_patch("line_ids", 1, 101)
        self.cache.add_patch("line_ids", 2, 200)

        patches = self.cache.get_patches("line_ids")
        self.assertEqual(patches[1], [100, 101])
        self.assertEqual(patches[2], [200])


class TestFieldCacheInvalidation(unittest.TestCase):
    """Test invalidation (per-field, per-id, all)."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.cache.set_value("name", 1, "Alice")
        self.cache.set_value("name", 2, "Bob")
        self.cache.set_value("email", 1, "alice@x.com")

    def test_invalidate_field_all(self) -> None:
        self.cache.invalidate_field("name")
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.has_value("name", 2))
        # other field untouched
        self.assertTrue(self.cache.has_value("email", 1))

    def test_invalidate_field_specific_ids(self) -> None:
        self.cache.invalidate_field("name", [1])
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertTrue(self.cache.has_value("name", 2))

    def test_invalidate_field_nonexistent(self) -> None:
        # should not raise
        self.cache.invalidate_field("nonexistent")
        self.cache.invalidate_field("nonexistent", [1])

    def test_invalidate_field_specific_ids_context_dependent(self) -> None:
        # Context-dependent fields (translate=True, company_dependent) store
        # ``{cache_key_tuple: {id: value}}``.  The per-id branch must scrub
        # the ids inside every cache_key sub-dict (it used to silently no-op
        # on this shape), mirroring ``invalidate_all``'s tuple detection.
        cache = FieldCache()
        cache._data["G"][("en_US",)] = {1: "one_en", 2: "two_en"}
        cache._data["G"][("es_MX",)] = {1: "one_es", 3: "three_es"}
        cache.invalidate_field("G", [1])
        self.assertEqual(cache._data["G"][("en_US",)], {2: "two_en"})
        self.assertEqual(cache._data["G"][("es_MX",)], {3: "three_es"})

    def test_invalidate_field_context_dependent_drops_emptied_cache_key(self) -> None:
        cache = FieldCache()
        cache._data["G"][("en_US",)] = {1: "one_en"}
        cache._data["G"][("es_MX",)] = {1: "one_es", 2: "two_es"}
        cache.invalidate_field("G", [1])
        # the fully-scrubbed cache_key entry is removed, the other trimmed
        self.assertNotIn(("en_US",), cache._data["G"])
        self.assertEqual(cache._data["G"][("es_MX",)], {2: "two_es"})

    def test_invalidate_field_flat_dict_valued_stays_flat(self) -> None:
        # Flat fields with dict VALUES (Json, Properties) must not be treated
        # as context-dependent: shape detection keys on tuple KEYS only.
        cache = FieldCache()
        cache._data["json_f"] = {1: {"k": "v1"}, 2: {"k": "v2"}}
        cache.invalidate_field("json_f", [1])
        self.assertFalse(cache.has_value("json_f", 1))
        self.assertEqual(cache.get_value("json_f", 2), {"k": "v2"})

    def test_invalidate_all(self) -> None:
        self.cache.invalidate_all()
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.has_value("email", 1))

    def test_invalidate_all_preserves_dirty(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.invalidate_all()
        # dirty flags survive invalidate_all
        self.assertTrue(self.cache.is_any_dirty())

    def test_invalidate_all_evicts_clean_on_dirty_field(self) -> None:
        # Regression for H1 (audit round 1):
        # ``invalidate_all`` previously preserved the *entire* sub-dict of
        # any field with at least one dirty entry — including non-dirty
        # record IDs.  The contract documented in the docstring is that
        # only dirty entries survive.
        self.cache.mark_dirty("name", [1])
        self.cache.invalidate_all()
        # dirty entry preserved
        self.assertTrue(self.cache.has_value("name", 1))
        self.assertEqual(self.cache.get_value("name", 1), "Alice")
        # clean entry on the same field MUST be evicted
        self.assertFalse(self.cache.has_value("name", 2))
        # clean field with no dirty entries is fully cleared
        self.assertFalse(self.cache.has_value("email", 1))

    def test_invalidate_all_context_dep_evicts_clean(self) -> None:
        # Regression for H1: context-dependent shape ``{cache_key: {id: v}}``.
        # Each cache_key sub-dict must drop non-dirty IDs, and an emptied
        # cache_key entry must be removed.
        cache = FieldCache()
        cache._data["G"][("en_US",)] = {1: "dirty_en", 2: "clean_en"}
        cache._data["G"][("es_MX",)] = {1: "dirty_es", 3: "clean_es_only"}
        cache.mark_dirty("G", [1])
        cache.invalidate_all()
        # both cache_keys keep id=1, drop the rest
        self.assertEqual(cache._data["G"][("en_US",)], {1: "dirty_en"})
        self.assertEqual(cache._data["G"][("es_MX",)], {1: "dirty_es"})

    def test_invalidate_all_flat_dict_valued_preserves_dirty(self) -> None:
        # Regression for the shape-detection bug fixed 2026-05-04: flat fields
        # whose values are themselves Python dicts (Json, Properties) were
        # mis-classified as context-dependent because the heuristic checked
        # ``isinstance(v, dict)``.  The dirty entry was silently evicted.
        # Switching to ``isinstance(k, tuple)`` (cache_keys are tuples,
        # record ids are not) fixes the misclassification.
        cache = FieldCache()
        cache._data["json_f"] = {1: {"k": "v1"}, 2: {"k": "v2"}}
        cache._data["props_f"] = {1: {"prio": "high"}, 2: {"prio": "low"}}
        cache.mark_dirty("json_f", [1])
        cache.mark_dirty("props_f", [1])
        cache.invalidate_all()
        # dirty record 1 must survive in both flat dict-valued fields
        self.assertEqual(cache._data["json_f"], {1: {"k": "v1"}})
        self.assertEqual(cache._data["props_f"], {1: {"prio": "high"}})

    def test_clear_everything(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.add_patch("line_ids", 1, 100)
        self.cache.clear()
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.is_any_dirty())
        self.assertIsNone(self.cache.get_patches("line_ids"))


class TestFieldCacheIntrospection(unittest.TestCase):
    """Test iteration and repr."""

    def setUp(self) -> None:
        self.cache = FieldCache()

    def test_iter_field_items(self) -> None:
        self.cache.set_value("name", 1, "Alice")
        items = list(self.cache.iter_field_items())
        self.assertEqual(len(items), 1)
        field, data = items[0]
        self.assertEqual(field, "name")
        self.assertEqual(data, {1: "Alice"})

    def test_repr(self) -> None:
        self.cache.set_value("name", 1, "Alice")
        self.cache.mark_dirty("name", [1])
        r = repr(self.cache)
        self.assertIn("fields=1", r)
        self.assertIn("dirty_entries=1", r)


class _MockField:
    """Minimal mock with model_name for pop_dirty_for_model tests."""

    def __init__(self, name: str, model_name: str) -> None:
        self.name = name
        self.model_name = model_name

    def __repr__(self) -> str:
        return f"<MockField {self.model_name}.{self.name}>"

    def __hash__(self) -> int:
        return hash((self.model_name, self.name))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _MockField)
            and self.model_name == other.model_name
            and self.name == other.name
        )


class TestPopDirtyForModel(unittest.TestCase):
    """Test pop_dirty_for_model() — filters by model_name attribute."""

    def setUp(self) -> None:
        self.cache = FieldCache()
        self.f_partner_name = _MockField("name", "res.partner")
        self.f_partner_email = _MockField("email", "res.partner")
        self.f_order_name = _MockField("name", "sale.order")

    def test_pops_matching_model(self) -> None:
        self.cache.mark_dirty(self.f_partner_name, [1, 2])
        self.cache.mark_dirty(self.f_partner_email, [3])
        self.cache.mark_dirty(self.f_order_name, [10])

        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[self.f_partner_name], {1, 2})
        self.assertEqual(result[self.f_partner_email], {3})

        # sale.order dirty entry should remain
        self.assertTrue(self.cache.has_dirty_field(self.f_order_name))
        # res.partner entries should be gone
        self.assertFalse(self.cache.has_dirty_field(self.f_partner_name))
        self.assertFalse(self.cache.has_dirty_field(self.f_partner_email))

    def test_returns_empty_for_no_match(self) -> None:
        self.cache.mark_dirty(self.f_order_name, [10])
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})
        # sale.order still dirty
        self.assertTrue(self.cache.has_dirty_field(self.f_order_name))

    def test_returns_empty_when_no_dirty(self) -> None:
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})

    def test_empty_mark_yields_nothing_to_pop(self) -> None:
        """An empty mark_dirty never registers the field (the _dirty invariant).

        Previously ``mark_dirty`` could vivify an empty set, which
        ``pop_dirty_for_model`` then had to filter out with an ``if ids`` guard.
        The field is now never registered in the first place.
        """
        self.cache.mark_dirty(self.f_partner_name, [])
        self.assertNotIn(self.f_partner_name, self.cache._dirty)
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
