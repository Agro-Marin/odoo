import json
from datetime import date, datetime

from odoo.tests.common import TransactionCase


class TestJsonFieldTypes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Discussion = cls.env["test_orm.discussion"]

    def _create(self, history=None):
        vals = {"name": "JSON Test"}
        if history is not None:
            vals["history"] = history
        return self.Discussion.create(vals)

    def test_default_value(self):
        disc = self._create()
        self.assertEqual(disc.history, {"delete_messages": []})

    def test_read_write_dict(self):
        disc = self._create({"key": "value", "count": 42})
        self.assertEqual(disc.history, {"key": "value", "count": 42})

    def test_read_write_list(self):
        disc = self._create([1, 2, 3])
        self.assertEqual(disc.history, [1, 2, 3])

    def test_tuple_converted_to_list(self):
        disc = self._create()
        disc.history = ("a", "b")
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history, ["a", "b"])

    def test_read_write_nested(self):
        nested = {
            "level1": {
                "level2": {
                    "level3": [1, {"key": [True, None, "text"]}],
                }
            }
        }
        disc = self._create(nested)
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history, nested)

    def test_read_write_scalar_string(self):
        disc = self._create("just a string")
        self.assertEqual(disc.history, "just a string")

    def test_read_write_scalar_number(self):
        disc = self._create(42)
        self.assertEqual(disc.history, 42)

        disc.history = 3.14
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertAlmostEqual(disc.history, 3.14)

    def test_read_write_scalar_bool(self):
        disc = self._create(True)
        self.assertEqual(disc.history, True)

    def test_read_write_null(self):
        disc = self._create()
        disc.history = None
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_falsy_empty_dict(self):
        disc = self._create()
        disc.history = {}
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_falsy_empty_list(self):
        disc = self._create()
        disc.history = []
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_falsy_zero(self):
        disc = self._create()
        disc.history = 0
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_falsy_empty_string(self):
        disc = self._create()
        disc.history = ""
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_falsy_false(self):
        disc = self._create()
        disc.history = False
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)


class TestJsonFieldCacheIsolation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.disc = cls.env["test_orm.discussion"].create(
            {
                "name": "Cache Isolation",
                "history": {"items": [1, 2, 3]},
            }
        )

    def test_deepcopy_on_read(self):
        val1 = self.disc.history
        val2 = self.disc.history
        self.assertEqual(val1, val2)
        self.assertIsNot(val1, val2)

    def test_mutation_isolation(self):
        val = self.disc.history
        val["items"].append(999)
        val["new_key"] = "added"

        fresh = self.disc.history
        self.assertEqual(fresh, {"items": [1, 2, 3]})
        self.assertNotIn("new_key", fresh)

    def test_cache_roundtrip(self):
        self.disc.history = {"b": 2, "a": 1}
        result = self.disc.history
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)


class TestJsonFieldPersistence(TransactionCase):
    def test_flush_and_reload(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Persistence Test",
                "history": {"persisted": True, "count": 42},
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()

        reloaded = self.env["test_orm.discussion"].browse(disc.id)
        self.assertEqual(reloaded.history, {"persisted": True, "count": 42})

    def test_write_none_clears(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Clear Test",
                "history": {"data": "exists"},
            }
        )
        disc.history = None
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertFalse(disc.history)

    def test_write_overwrite(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Overwrite Test",
                "history": {"first": 1},
            }
        )
        disc.history = {"second": 2}
        disc.flush_recordset()
        disc.invalidate_recordset()
        result = disc.history
        self.assertEqual(result, {"second": 2})
        self.assertNotIn("first", result)

    def test_create_with_json(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Created JSON",
                "history": {"created": True},
            }
        )
        self.assertEqual(disc.history, {"created": True})

    def test_batch_create_with_json(self):
        records = self.env["test_orm.discussion"].create(
            [
                {"name": "Batch 1", "history": {"idx": 1}},
                {"name": "Batch 2", "history": {"idx": 2}},
                {"name": "Batch 3", "history": {"idx": 3}},
            ]
        )
        self.assertEqual(records[0].history, {"idx": 1})
        self.assertEqual(records[1].history, {"idx": 2})
        self.assertEqual(records[2].history, {"idx": 3})

    def test_copy_json(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Copy Source",
                "history": {"source": True, "items": [1, 2]},
            }
        )
        disc_copy = disc.copy()
        self.assertEqual(disc_copy.history, {"source": True, "items": [1, 2]})
        disc_copy.history = {"modified": True}
        disc_copy.flush_recordset()
        self.assertEqual(disc.history, {"source": True, "items": [1, 2]})

    def test_search_read_includes_json(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "SearchRead JSON",
                "history": {"sr": True},
            }
        )
        results = self.env["test_orm.discussion"].search_read(
            [("id", "=", disc.id)],
            ["name", "history"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["history"], {"sr": True})


class TestJsonFieldExport(TransactionCase):
    def test_export_dict(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Export Dict",
                "history": {"key": "value"},
            }
        )
        field = disc._fields["history"]
        result = field.convert_to_export(disc.history, disc)
        self.assertIsInstance(result, str)
        self.assertEqual(json.loads(result), {"key": "value"})

    def test_export_list(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Export List",
                "history": [1, 2, 3],
            }
        )
        field = disc._fields["history"]
        result = field.convert_to_export(disc.history, disc)
        self.assertEqual(json.loads(result), [1, 2, 3])

    def test_export_falsy(self):
        disc = self.env["test_orm.discussion"].create({"name": "Export None"})
        disc.history = None
        disc.flush_recordset()
        disc.invalidate_recordset()
        field = disc._fields["history"]
        result = field.convert_to_export(disc.history, disc)
        self.assertEqual(result, "")


class TestJsonFieldEdgeCases(TransactionCase):
    def test_unicode_characters(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Unicode JSON",
                "history": {
                    "greeting": "Hola mundo",
                    "emoji": "🎉🎊",
                    "chinese": "你好",
                },
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history["greeting"], "Hola mundo")
        self.assertEqual(disc.history["emoji"], "🎉🎊")
        self.assertEqual(disc.history["chinese"], "你好")

    def test_special_json_chars(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Special Chars",
                "history": {
                    "quote": 'He said "hello"',
                    "backslash": "C:\\path",
                    "newline": "line1\nline2",
                },
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history["quote"], 'He said "hello"')
        self.assertEqual(disc.history["backslash"], "C:\\path")
        self.assertIn("\n", disc.history["newline"])

    def test_large_json(self):
        large = {f"key_{i}": f"value_{i}" for i in range(500)}
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Large JSON",
                "history": large,
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(len(disc.history), 500)
        self.assertEqual(disc.history["key_0"], "value_0")
        self.assertEqual(disc.history["key_499"], "value_499")

    def test_json_with_date_via_default(self):
        today = date.today()
        now = datetime.now()
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Date JSON",
                "history": {"date": today, "datetime": now},
            }
        )
        result = disc.history
        self.assertIsInstance(result["date"], str)
        self.assertIsInstance(result["datetime"], str)

    def test_numeric_precision(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Numeric JSON",
                "history": {"big_int": 9999999999999, "float": 1.23456789},
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history["big_int"], 9999999999999)
        self.assertAlmostEqual(disc.history["float"], 1.23456789)

    def test_null_in_nested(self):
        disc = self.env["test_orm.discussion"].create(
            {
                "name": "Nested Null",
                "history": {"items": [None, 1, None, "text"]},
            }
        )
        disc.flush_recordset()
        disc.invalidate_recordset()
        self.assertEqual(disc.history["items"], [None, 1, None, "text"])
