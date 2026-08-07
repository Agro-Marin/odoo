from odoo.tests.common import TransactionCase, get_cache_key_counter

from odoo.addons.base.models.properties_base_definition import (
    DEFINITION_MEMO_CACHE_KEY,
)


class DeliberateRollback(Exception):
    pass


class TestPropertiesBaseDefinition(TransactionCase):
    MODEL = "res.partner"
    FIELD = "properties"

    def setUp(self):
        super().setUp()
        self.Definition = self.env["properties.base.definition"]
        field = self.env["ir.model.fields"]._get(self.MODEL, self.FIELD)
        self.Definition.sudo().search([("properties_field_id", "=", field.id)]).unlink()
        self.registry.clear_cache("stable")
        self.env.cr.cache.pop(DEFINITION_MEMO_CACHE_KEY, None)

    def _get_definition_id(self):
        return self.Definition._get_definition_id_for_property_field(
            self.MODEL, self.FIELD
        )

    def _stable_cache_and_key(self):
        cache, key, _counter = get_cache_key_counter(
            self.Definition._search_definition_id_for_property_field,
            self.MODEL,
            self.FIELD,
        )
        return cache, key

    def _count_rows(self):
        field = self.env["ir.model.fields"]._get(self.MODEL, self.FIELD)
        return self.Definition.sudo().search_count(
            [("properties_field_id", "=", field.id)]
        )

    def test_create_on_miss_memoized_transaction_locally_only(self):
        definition_id = self._get_definition_id()
        self.assertTrue(definition_id)
        self.assertEqual(self._count_rows(), 1)

        cache, key = self._stable_cache_and_key()
        self.assertNotIn(
            key,
            cache,
            "a definition id created by the current transaction must not be "
            "memoized in the registry-wide stable cache",
        )
        memo = self.env.cr.cache.get(DEFINITION_MEMO_CACHE_KEY) or {}
        self.assertEqual(memo.get((self.MODEL, self.FIELD)), definition_id)

        self.assertEqual(self._get_definition_id(), definition_id)
        self.assertEqual(
            self.Definition._get_definition_for_property_field(
                self.MODEL, self.FIELD
            ).id,
            definition_id,
        )
        self.assertEqual(self._count_rows(), 1)

    def test_rollback_leaves_no_dangling_cache_entry(self):
        with self.assertRaises(DeliberateRollback), self.env.cr.savepoint():
            first_id = self._get_definition_id()
            self.assertTrue(first_id)
            raise DeliberateRollback

        cache, key = self._stable_cache_and_key()
        self.assertNotIn(key, cache)
        memo = self.env.cr.cache.get(DEFINITION_MEMO_CACHE_KEY) or {}
        self.assertNotIn((self.MODEL, self.FIELD), memo)
        self.assertEqual(self._count_rows(), 0)

        second_id = self._get_definition_id()
        self.assertNotEqual(second_id, first_id)
        self.assertTrue(self.Definition.sudo().browse(second_id).exists())
        self.assertEqual(self._count_rows(), 1)

    def test_select_hit_populates_stable_cache(self):
        definition_id = self._get_definition_id()
        self.env.cr.cache.pop(DEFINITION_MEMO_CACHE_KEY, None)

        self.assertEqual(self._get_definition_id(), definition_id)
        cache, key = self._stable_cache_and_key()
        self.assertEqual(
            cache.get(key),
            definition_id,
            "an id found by SELECT must be memoized in the stable cache",
        )
        self.assertEqual(self._count_rows(), 1)
