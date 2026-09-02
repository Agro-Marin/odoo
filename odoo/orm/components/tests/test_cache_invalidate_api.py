import unittest

from odoo.orm.components.cache import FieldCache


class TestInvalidateFlat(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = FieldCache()
        self.cache.set_value("name", 1, "Alice")
        self.cache.set_value("name", 2, "Bob")
        self.cache.set_value("email", 1, "alice@x.com")

    def test_specific_ids(self) -> None:
        self.cache.invalidate("name", [1])
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertTrue(self.cache.has_value("name", 2))
        self.assertTrue(self.cache.has_value("email", 1))

    def test_all_ids(self) -> None:
        self.cache.invalidate("name", None)
        self.assertFalse(self.cache.has_value("name", 1))
        self.assertFalse(self.cache.has_value("name", 2))
        self.assertTrue(self.cache.has_value("email", 1))

    def test_flat_clear_preserves_dict_identity(self) -> None:
        live = self.cache.get_field_data("name")
        self.cache.invalidate("name", None)
        self.assertIs(self.cache.get_field_data("name"), live)
        self.assertEqual(live, {})

    def test_nonexistent_field_is_noop(self) -> None:
        self.cache.invalidate("missing", None)
        self.cache.invalidate("missing", [1])
        self.assertIsNone(self.cache.get_field_data_or_none("missing"))

    def test_dict_valued_flat_cache_pops_whole_entries(self) -> None:
        cache = FieldCache()
        cache.get_field_data("json_f").update({1: {"k": "v1"}, 2: {"k": "v2"}})
        cache.invalidate("json_f", [1])
        self.assertFalse(cache.has_value("json_f", 1))
        self.assertEqual(cache.get_value("json_f", 2), {"k": "v2"})

    def test_dirty_flags_are_untouched(self) -> None:
        self.cache.mark_dirty("name", [1])
        self.cache.invalidate("name", [1])
        self.assertTrue(self.cache.has_dirty_field("name"))


class TestInvalidateContextDependent(unittest.TestCase):
    def _make(self) -> FieldCache:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "one_en", 2: "two_en"})
        cache.get_context_data("G", ("es_MX",)).update({1: "one_es", 3: "three_es"})
        return cache

    def test_specific_ids_scrub_every_context(self) -> None:
        cache = self._make()
        cache.invalidate("G", [1])
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {2: "two_en"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {3: "three_es"})

    def test_emptied_subdict_is_kept_in_place(self) -> None:
        cache = self._make()
        en_sub = cache.get_context_data("G", ("en_US",))
        cache.invalidate("G", [1, 2])
        self.assertIs(cache.get_context_data("G", ("en_US",)), en_sub)
        self.assertEqual(en_sub, {})

    def test_all_ids_clears_subdicts_in_place(self) -> None:
        cache = self._make()
        en_sub = cache.get_context_data("G", ("en_US",))
        es_sub = cache.get_context_data("G", ("es_MX",))
        cache.invalidate("G", None)
        self.assertIs(cache.get_context_data("G", ("en_US",)), en_sub)
        self.assertIs(cache.get_context_data("G", ("es_MX",)), es_sub)
        self.assertEqual(en_sub, {})
        self.assertEqual(es_sub, {})

    def test_a_flat_entry_beside_the_contexts_is_evicted_too(self) -> None:
        cache = self._make()
        flat = cache.get_field_data("G")
        flat[5] = "flat-scalar"
        flat[1] = {3: "json-payload"}
        cache.invalidate("G", [1, 5])
        self.assertEqual(flat, {})
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {2: "two_en"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {3: "three_es"})

    def test_never_pops_inside_json_values(self) -> None:
        cache = self._make()
        flat = cache.get_field_data("G")
        flat[1] = {3: "json-payload"}
        cache.invalidate("G", [3])
        self.assertEqual(flat[1], {3: "json-payload"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {1: "one_es"})

    def test_all_ids_drops_flat_entries_beside_the_contexts(self) -> None:
        cache = self._make()
        cache.get_field_data("G")[5] = "flat-scalar"
        cache.invalidate("G", None)
        self.assertEqual(cache.get_field_data("G"), {})
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {})


class TestAllCachedIds(unittest.TestCase):
    def test_flat_returns_live_mapping(self) -> None:
        cache = FieldCache()
        cache.set_value("name", 1, "a")
        cache.set_value("name", 2, "b")
        ids = cache.all_cached_ids("name")
        self.assertEqual(set(ids), {1, 2})
        self.assertEqual(set(ids.keys()), {1, 2})

    def test_empty_field_returns_empty_and_does_not_vivify(self) -> None:
        cache = FieldCache()
        self.assertFalse(cache.all_cached_ids("never"))
        self.assertFalse(cache.all_context_cached_ids("never"))
        self.assertIsNone(cache.get_field_data_or_none("never"))
        self.assertEqual(list(cache.cached_fields()), [])

    def test_context_merges_subdict_ids(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "a", 2: "b"})
        cache.get_context_data("G", ("es_MX",)).update({2: "c", 3: "d"})
        ids = cache.all_context_cached_ids("G")
        self.assertEqual(set(ids), {1, 2, 3})
        self.assertTrue(ids)

    def test_context_ignores_the_flat_store(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",))[1] = "a"
        cache.get_field_data("G").update({7: {"json-key": "v"}, 8: "flat-scalar"})
        self.assertEqual(set(cache.all_context_cached_ids("G")), {1})
        self.assertEqual(set(cache.all_cached_ids("G")), {7, 8})

    def test_context_with_only_flat_entries_yields_empty(self) -> None:
        cache = FieldCache()
        cache.get_field_data("G")[8] = "flat-scalar"
        ids = cache.all_context_cached_ids("G")
        self.assertEqual(set(ids), set())
        self.assertFalse(ids)


class TestKeepDirty(unittest.TestCase):
    def test_flat_all_ids_keeps_dirty_values(self) -> None:
        cache = FieldCache()
        cache.set_value("partner_id", 1, 10)
        cache.set_value("partner_id", 2, 20)
        cache.mark_dirty("partner_id", [1])
        cache.invalidate("partner_id", None, keep_dirty=True)
        self.assertEqual(cache.get_value("partner_id", 1), 10)
        self.assertFalse(cache.has_value("partner_id", 2))

    def test_flat_specific_ids_keeps_dirty_values(self) -> None:
        cache = FieldCache()
        cache.set_value("partner_id", 1, 10)
        cache.set_value("partner_id", 2, 20)
        cache.mark_dirty("partner_id", [1])
        cache.invalidate("partner_id", [1, 2], keep_dirty=True)
        self.assertEqual(cache.get_value("partner_id", 1), 10)
        self.assertFalse(cache.has_value("partner_id", 2))

    def test_flat_clear_preserves_dict_identity(self) -> None:
        cache = FieldCache()
        cache.set_value("partner_id", 1, 10)
        cache.mark_dirty("partner_id", [1])
        live = cache.get_field_data("partner_id")
        cache.invalidate("partner_id", None, keep_dirty=True)
        self.assertIs(cache.get_field_data("partner_id"), live)

    def test_context_all_ids_keeps_dirty_across_subcaches(self) -> None:
        cache = FieldCache()
        live = cache.get_context_data("G", ("en_US",))
        live.update({1: "one_en", 2: "two_en"})
        cache.get_context_data("G", ("es_MX",)).update({1: "one_es", 2: "two_es"})
        cache.mark_dirty("G", [1])
        cache.invalidate("G", None, keep_dirty=True)
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {1: "one_en"})
        self.assertEqual(cache.get_context_data("G", ("es_MX",)), {1: "one_es"})
        self.assertIs(cache.get_context_data("G", ("en_US",)), live)

    def test_context_specific_ids_keeps_dirty(self) -> None:
        cache = FieldCache()
        cache.get_context_data("G", ("en_US",)).update({1: "one_en", 2: "two_en"})
        cache.mark_dirty("G", [1])
        cache.invalidate("G", [1, 2], keep_dirty=True)
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {1: "one_en"})

    def test_a_dirty_flat_entry_beside_the_contexts_is_kept(self) -> None:
        cache = FieldCache()
        cache.get_field_data("G").update({8: "flat-scalar", 9: "flat-scalar-2"})
        cache.get_context_data("G", ("en_US",))[9] = "nine_en"
        cache.mark_dirty("G", [8])
        cache.invalidate("G", None, keep_dirty=True)
        self.assertEqual(cache.get_field_data("G"), {8: "flat-scalar"})
        self.assertEqual(cache.get_context_data("G", ("en_US",)), {})

    def test_default_still_drops_dirty_values(self) -> None:
        cache = FieldCache()
        cache.set_value("partner_id", 1, 10)
        cache.mark_dirty("partner_id", [1])
        cache.invalidate("partner_id", None)
        self.assertFalse(cache.has_value("partner_id", 1))
        self.assertTrue(cache.has_dirty_field("partner_id"))

    def test_keep_dirty_does_not_clear_the_dirty_flags(self) -> None:
        cache = FieldCache()
        cache.set_value("partner_id", 1, 10)
        cache.mark_dirty("partner_id", [1])
        cache.invalidate("partner_id", None, keep_dirty=True)
        self.assertEqual(cache.get_dirty("partner_id"), {1})


if __name__ == "__main__":
    unittest.main()
