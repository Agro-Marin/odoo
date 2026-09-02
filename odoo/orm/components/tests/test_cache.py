import unittest

from odoo.orm.components.cache import FieldCache


def _present[T](value: T | None) -> T:
    assert value is not None, "the component under test returned None"
    return value


class TestFieldCacheData(unittest.TestCase):
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
        self.cache.get_value("ghost", 1, default=None)
        self.assertNotIn("ghost", dict(self.cache.iter_field_items()))
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
        d[1] = "Bob"
        self.assertEqual(self.cache.get_value("name", 1), "Bob")

    def test_get_field_data_or_none(self) -> None:
        self.assertIsNone(self.cache.get_field_data_or_none("name"))
        self.cache.set_value("name", 1, "Alice")
        self.assertIsNotNone(self.cache.get_field_data_or_none("name"))


class TestFieldCacheDirty(unittest.TestCase):
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
        self.assertEqual(len(_present(self.cache.get_dirty("name"))), 1)

    def test_mark_dirty_empty_creates_no_phantom(self) -> None:
        self.cache.mark_dirty("name", [])
        self.assertFalse(self.cache.is_any_dirty())
        self.assertNotIn("name", list(self.cache.iter_dirty_fields()))
        empty: list[int] = []
        self.cache.mark_dirty("ref", (i for i in empty if i))
        self.assertFalse(self.cache.is_any_dirty())
        self.assertEqual(self.cache.dirty_entry_count(), 0)

    def test_mark_dirty_empty_keeps_existing(self) -> None:
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
        class OrderedSet(set):
            pass

        cache = FieldCache(dirty_factory=OrderedSet)
        cache.mark_dirty("name", [1, 2])
        dirty = cache.get_dirty("name")
        self.assertIsInstance(dirty, OrderedSet)
        self.assertEqual(dirty, {1, 2})


class TestFieldCachePatches(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = FieldCache()

    def test_no_patches(self) -> None:
        self.assertIsNone(self.cache.get_patches("line_ids"))

    def test_add_and_get_patch(self) -> None:
        self.cache.add_patch("line_ids", 1, 100)
        self.cache.add_patch("line_ids", 1, 101)
        self.cache.add_patch("line_ids", 2, 200)

        patches = _present(self.cache.get_patches("line_ids"))
        self.assertEqual(patches[1], [100, 101])
        self.assertEqual(patches[2], [200])


class TestFieldCacheInvalidation(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = FieldCache()
        self.cache.set_value("name", 1, "Alice")
        self.cache.set_value("name", 2, "Bob")
        self.cache.set_value("email", 1, "alice@x.com")

    def test_invalidate_whole_field(self) -> None:
        self.cache.invalidate("name")
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.has_value("name", 2))
        self.assertTrue(self.cache.has_value("email", 1))

    def test_invalidate_specific_ids(self) -> None:
        self.cache.invalidate("name", [1])
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertTrue(self.cache.has_value("name", 2))

    def test_invalidate_nonexistent(self) -> None:
        self.cache.invalidate("nonexistent")
        self.cache.invalidate("nonexistent", [1])
        self.assertIsNone(self.cache.get_field_data_or_none("nonexistent"))
        self.assertEqual(list(self.cache.iter_context_caches("nonexistent")), [])

    def test_invalidate_specific_ids_context_dependent(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "one_en", 2: "two_en"})
        cache.get_context_data("G", ("es_MX",)).update({1: "one_es", 3: "three_es"})
        cache.invalidate("G", [1])
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {2: "two_en"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {3: "three_es"})

    def test_invalidate_context_dependent_keeps_the_emptied_sub_cache(self) -> None:
        cache = FieldCache()
        en = cache.get_context_data("G", ("en_US",))
        en[1] = "one_en"
        cache.get_context_data("G", ("es_MX",)).update({1: "one_es", 2: "two_es"})
        cache.invalidate("G", [1])
        self.assertIs(cache.get_context_data_or_none("G", ("en_US",)), en)
        self.assertEqual(en, {})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {2: "two_es"})

    def test_invalidate_flat_dict_valued_stays_flat(self) -> None:
        cache = FieldCache()
        cache.get_field_data("json_f").update({1: {"k": "v1"}, 2: {"k": "v2"}})
        cache.invalidate("json_f", [1])
        self.assertFalse(cache.has_value("json_f", 1))
        self.assertEqual(cache.get_value("json_f", 2), {"k": "v2"})

    def test_invalidate_all(self) -> None:
        self.cache.invalidate_all()
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.has_value("email", 1))

    def test_invalidate_all_preserves_dirty(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.invalidate_all()
        self.assertTrue(self.cache.is_any_dirty())

    def test_invalidate_all_evicts_clean_on_dirty_field(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.invalidate_all()
        self.assertTrue(self.cache.has_value("name", 1))
        self.assertEqual(self.cache.get_value("name", 1), "Alice")
        self.assertFalse(self.cache.has_value("name", 2))
        self.assertFalse(self.cache.has_value("email", 1))

    def test_invalidate_all_context_dep_evicts_clean(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "dirty_en", 2: "clean_en"})
        cache.get_context_data("G", ("es_MX",)).update({1: "dirty_es", 3: "clean_es"})
        cache.mark_dirty("G", [1])
        cache.invalidate_all()
        self.assertEqual(
            dict(cache.iter_context_caches("G")),
            {("en_US",): {1: "dirty_en"}, ("es_MX",): {1: "dirty_es"}},
        )

    def test_invalidate_all_drops_a_context_sub_cache_holding_nothing_dirty(
        self,
    ) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "dirty_en"})
        cache.get_context_data("G", ("es_MX",)).update({2: "clean_es"})
        cache.get_context_data("H", ("en_US",)).update({1: "clean_h"})
        cache.mark_dirty("G", [1])
        cache.invalidate_all()
        self.assertEqual(
            dict(cache.iter_context_caches("G")), {("en_US",): {1: "dirty_en"}}
        )
        self.assertEqual(list(cache.iter_context_caches("H")), [])
        self.assertEqual(set(cache.cached_fields()), {"G"})

    def test_invalidate_all_flat_dict_valued_preserves_dirty(self) -> None:
        cache = FieldCache()
        cache.get_field_data("json_f").update({1: {"k": "v1"}, 2: {"k": "v2"}})
        cache.get_field_data("props_f").update(
            {1: {"prio": "high"}, 2: {"prio": "low"}}
        )
        cache.mark_dirty("json_f", [1])
        cache.mark_dirty("props_f", [1])
        cache.invalidate_all()
        self.assertEqual(cache.get_field_data("json_f"), {1: {"k": "v1"}})
        self.assertEqual(cache.get_field_data("props_f"), {1: {"prio": "high"}})

    def test_clear_everything(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.add_patch("line_ids", 1, 100)
        self.cache.clear()
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.is_any_dirty())
        self.assertIsNone(self.cache.get_patches("line_ids"))


class TestFieldCacheTwoStores(unittest.TestCase):
    def _both_stores(self) -> FieldCache:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "one_en", 2: "two_en"})
        cache.get_context_data("G", ("es_MX",)).update({1: "one_es", 3: "three_es"})
        cache.get_field_data("G")[99] = "flat-value"
        return cache

    def test_get_context_data_creates_and_returns_the_live_sub_cache(self) -> None:
        cache = FieldCache()
        sub = cache.get_context_data("G", ("en_US",))
        self.assertEqual(sub, {})
        sub[1] = "x"
        self.assertIs(cache.get_context_data("G", ("en_US",)), sub)
        self.assertIs(cache.get_context_data_or_none("G", ("en_US",)), sub)

    def test_get_context_data_or_none_does_not_vivify(self) -> None:
        cache = FieldCache()
        self.assertIsNone(cache.get_context_data_or_none("G", ("en_US",)))
        self.assertEqual(list(cache.iter_context_caches("G")), [])
        self.assertEqual(list(cache.cached_fields()), [])

    def test_the_flat_store_and_the_context_store_do_not_see_each_other(self) -> None:
        cache = self._both_stores()
        self.assertEqual(cache.get_field_data("G"), {99: "flat-value"})
        self.assertEqual(set(cache.all_cached_ids("G")), {99})
        self.assertEqual(set(cache.all_context_cached_ids("G")), {1, 2, 3})
        self.assertNotIn(99, cache.all_context_cached_ids("G"))
        self.assertTrue(cache.has_any_cached("G"))
        self.assertTrue(cache.has_any_context_cached("G"))

    def test_has_any_context_cached_needs_a_value_not_a_sub_cache(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",))
        self.assertFalse(cache.has_any_context_cached("G"))
        self.assertFalse(cache.has_any_cached("G"))
        cache.get_context_data("G", ("en_US",))[1] = "x"
        self.assertTrue(cache.has_any_context_cached("G"))
        self.assertFalse(cache.has_any_cached("G"))

    def test_invalidate_accepts_an_iterator(self) -> None:
        cache = self._both_stores()
        cache.invalidate("G", (i for i in (1, 2, 99)))
        self.assertEqual(
            dict(cache.iter_context_caches("G")),
            {("en_US",): {}, ("es_MX",): {3: "three_es"}},
        )
        self.assertEqual(cache.get_field_data("G"), {})

    def test_invalidate_iterator_matches_list(self) -> None:
        cache_list, cache_iter = self._both_stores(), self._both_stores()
        cache_list.invalidate("G", [1, 3])
        cache_iter.invalidate("G", iter([1, 3]))
        self.assertEqual(
            dict(cache_iter.iter_context_caches("G")),
            dict(cache_list.iter_context_caches("G")),
        )

    def test_invalidate_reaches_both_stores(self) -> None:
        cache = self._both_stores()
        cache.invalidate("G")
        self.assertEqual(cache.get_field_data("G"), {})
        self.assertEqual(
            dict(cache.iter_context_caches("G")), {("en_US",): {}, ("es_MX",): {}}
        )

    def test_iter_context_caches_yields_live_sub_dicts(self) -> None:
        cache = self._both_stores()
        for _key, sub in cache.iter_context_caches("G"):
            sub.pop(1, None)
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {2: "two_en"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {3: "three_es"})

    def test_iter_context_caches_on_unknown_field(self) -> None:
        cache = FieldCache()
        self.assertEqual(list(cache.iter_context_caches("nope")), [])

    def test_cached_fields_is_the_union_of_both_stores(self) -> None:
        cache = FieldCache()
        cache.set_value("flat", 1, "a")
        cache.get_context_data("ctx", ("en_US",))[1] = "b"
        self.assertEqual(set(cache.cached_fields()), {"flat", "ctx"})
        self.assertEqual(dict(cache.iter_field_items()), {"flat": {1: "a"}})

    def test_all_context_cached_ids_prefers_no_context_over_another(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "a", 2: "b"})
        cache.get_context_data("G", ("es_MX",)).update({2: "c", 3: "d"})
        ids = cache.all_context_cached_ids("G")
        self.assertEqual(set(ids), {1, 2, 3})
        self.assertTrue(ids)
        self.assertFalse(cache.all_context_cached_ids("never"))
        self.assertFalse(cache.all_cached_ids("never"))
        self.assertIsNone(cache.get_field_data_or_none("never"))


class TestFieldCacheIntrospection(unittest.TestCase):
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
        self.cache.get_context_data("scoped", ("x",))[1] = "s"
        self.cache.mark_dirty("name", [1])
        r = repr(self.cache)
        self.assertIn("fields=2", r)
        self.assertIn("dirty_entries=1", r)


class _MockField:
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

        self.assertTrue(self.cache.has_dirty_field(self.f_order_name))
        self.assertFalse(self.cache.has_dirty_field(self.f_partner_name))
        self.assertFalse(self.cache.has_dirty_field(self.f_partner_email))

    def test_returns_empty_for_no_match(self) -> None:
        self.cache.mark_dirty(self.f_order_name, [10])
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})
        self.assertTrue(self.cache.has_dirty_field(self.f_order_name))

    def test_returns_empty_when_no_dirty(self) -> None:
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})

    def test_empty_mark_yields_nothing_to_pop(self) -> None:
        self.cache.mark_dirty(self.f_partner_name, [])
        self.assertNotIn(self.f_partner_name, self.cache._dirty)
        result = self.cache.pop_dirty_for_model("res.partner")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
