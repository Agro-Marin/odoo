import unittest
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, can_import, loaded_demo_data, tagged
from odoo.tools.misc import file_open


@tagged("post_install", "-at_install")
class TestFieldConverters(TransactionCase):
    """Unit coverage for ``ir.fields.converter`` ``_str_to_*`` methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.converter = cls.env["ir.fields.converter"]
        # Keep Fields in a dict, not class attributes: a Field is a data
        # descriptor, so ``self.flds["dt"]`` would fire ``Field.__get__`` on the
        # TestCase (not a recordset) and raise.
        cls.flds = {
            "dt": cls.env["res.partner"]._fields["write_date"],
            "date": cls.env["res.partner"]._fields["write_date"],
            "bool": cls.env["res.partner"]._fields["is_company"],
            "m2o": cls.env["res.partner"]._fields["parent_id"],
            "float": cls.env["res.partner"]._fields["partner_latitude"],
        }

    def test_str_to_datetime_offset_bearing_iso_not_double_converted(self):
        """IFLD-01: an offset-bearing ISO string maps to the correct UTC instant.

        A tz-aware input must not be re-stamped with env.tz (double conversion).
        """
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.flds["dt"],
            "2026-03-19T16:09:18-06:00",
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2026-03-19 22:09:18")

    def test_str_to_datetime_naive_applies_input_tz(self):
        """IFLD-01 guard: the standard base_import (naive, offset-free) path
        still applies env.tz before storing as UTC."""
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.flds["dt"],
            "2026-03-19 16:09:18",
        )
        self.assertFalse(warnings)
        # 16:09:18 wall-clock at -06:00 == 22:09:18 UTC.
        self.assertEqual(value, "2026-03-19 22:09:18")

    def test_str_to_datetime_utc_z_suffix_not_double_converted(self):
        """IFLD-01: a ``Z`` (UTC) suffix is tz-aware and must not be re-stamped."""
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.flds["dt"],
            "2026-03-19T16:09:18Z",
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2026-03-19 16:09:18")

    def test_str_to_date_rejects_trailing_garbage(self):
        """IFLD-02: a date with trailing garbage must raise, not truncate."""
        with self.assertRaises(ValueError):
            self.converter._str_to_date(
                self.flds["date"],
                "2012-12-31xxx",
            )

    def test_str_to_date_valid(self):
        """IFLD-02 guard: a clean ISO date still converts."""
        value, warnings = self.converter._str_to_date(
            self.flds["date"],
            "2012-12-31",
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2012-12-31")

    def test_str_to_date_accepts_trailing_time(self):
        """IFLD-08: a date column carrying a time part must import as the plain
        date, not be rejected as trailing garbage (IFLD-02 rejects only a tail
        that is not a valid time)."""
        for value in (
            "2012-12-31 00:00:00",
            "2012-12-31T23:59:59",
            "2012-12-31 23:59:59",
        ):
            result, warnings = self.converter._str_to_date(self.flds["date"], value)
            self.assertFalse(warnings)
            self.assertEqual(result, "2012-12-31", "%r must import as its date" % value)
        # a tail that is not a valid time is still rejected
        for value in ("2012-12-31xxx", "2012-12-31 nope"):
            with self.assertRaises(ValueError):
                self.converter._str_to_date(self.flds["date"], value)

    def test_boolean_value_sets_built_once(self):
        """IFLD-09: true/false token sets are memoized per cursor, not rebuilt
        per boolean cell."""
        # drop any set cached by an earlier test on this shared cursor
        self.env.cr.cache.get("ir.fields.converter", {}).pop("boolean_value_sets", None)
        calls = []
        orig = type(self.converter)._get_boolean_translations

        def spy(this, src):
            calls.append(src)
            return orig(this, src)

        with patch.object(type(self.converter), "_get_boolean_translations", spy):
            for _ in range(50):
                # a value in neither set forces both to be consulted
                self.converter._str_to_boolean(self.flds["bool"], "maybe")
        # 4 lookups (true/yes/false/no) to build the sets once, then nothing.
        self.assertLessEqual(
            len(calls),
            4,
            "boolean token sets must be built a constant number of times, "
            "not once per converted cell",
        )

    def test_str_to_properties_does_not_mutate_input(self):
        """IFLD-10: coercing a list of property dicts must not mutate the
        caller's input."""
        original = [
            {"name": "x", "type": "integer", "string": "X", "value": "42"},
        ]
        snapshot = [dict(pd) for pd in original]
        result, _warnings = self.converter._str_to_properties(
            self.flds["bool"], original
        )
        self.assertEqual(original, snapshot, "input must not be mutated")
        self.assertIsNot(result, original, "output must be a fresh list")
        self.assertEqual(result[0]["value"], 42, "value must be coerced in output")

    def test_db_id_for_unknown_subfield_is_valueerror(self):
        """IFLD-11: an unknown referencing sub-field raises ``ValueError`` (caught
        by ``for_model`` into a per-field error), not a bare ``Exception`` that
        aborts ``load()``."""
        with self.assertRaises(ValueError):
            self.converter.db_id_for(self.flds["m2o"], "not_a_subfield", "x")

    def test_db_id_for_dbid_resolution(self):
        """IFLD-12: ``db_id_for`` on a ``.id`` reference resolves an existing
        record, returns ``False`` for an empty reference, and raises for an id
        matching no record."""
        partner = self.env["res.partner"].search([], limit=1)
        self.assertTrue(partner, "need at least one partner to resolve")
        got, warnings = self.converter.db_id_for(
            self.flds["m2o"], ".id", str(partner.id)
        )
        self.assertEqual(got, partner.id)
        self.assertFalse(warnings)
        # a falsy token is an empty reference, not an error
        empty, _w = self.converter.db_id_for(self.flds["m2o"], ".id", "0")
        self.assertIs(empty, False)
        # an id matching no record is an import error
        with self.assertRaises(ValueError):
            self.converter.db_id_for(self.flds["m2o"], ".id", str(partner.id + 10**9))

    def test_str_to_float_rejects_non_finite(self):
        """IFLD-13: reject non-finite floats ("nan"/"inf", overflowing exponents)
        with a clean import error rather than let them blow up in ``write()``;
        ordinary and scientific-notation numbers still parse."""
        for value in ("nan", "NaN", "inf", "-inf", "Infinity", "1e400"):
            with self.assertRaises(ValueError, msg="%r must be rejected" % value):
                self.converter._str_to_float(self.flds["float"], value)
        for value, expected in (("1.5", 1.5), (" 2.5 ", 2.5), ("1e3", 1000.0)):
            result, warnings = self.converter._str_to_float(self.flds["float"], value)
            self.assertFalse(warnings)
            self.assertEqual(result, expected)

    def test_str_to_boolean_unknown_returns_none(self):
        """IFLD-03: an unknown boolean yields ``None`` (not ``True``) + a warning."""
        value, warnings = self.converter._str_to_boolean(
            self.flds["bool"],
            "maybe",
        )
        self.assertIsNone(value)
        self.assertTrue(warnings)

    def test_str_to_boolean_known_values(self):
        """IFLD-03 guard: recognized true/false values still resolve."""
        true_val, _w = self.converter._str_to_boolean(self.flds["bool"], "1")
        false_val, _w = self.converter._str_to_boolean(self.flds["bool"], "0")
        self.assertIs(true_val, True)
        self.assertIs(false_val, False)

    def test_unsupported_field_type_logs_not_crash(self):
        """IFLD-07: a field type with no ``_str_to_<type>`` converter must log a
        per-field error, not raise an uncaught ``TypeError`` that aborts
        ``load()``."""
        target = None
        for model_name in self.env.registry.models:
            for fname, f in self.env[model_name]._fields.items():
                if not hasattr(self.converter, f"_str_to_{f.type}"):
                    target = (self.env[model_name], fname, f.type)
                    break
            if target:
                break
        if not target:
            self.skipTest("every field type has a converter on this build")
        model, fname, ftype = target
        fn = self.converter.for_model(model)
        logged = []
        # Must NOT raise.
        result = fn({fname: "x"}, lambda field, exc: logged.append((field, exc)))
        self.assertNotIn(fname, result, "unconvertible field must not be written")
        self.assertEqual([f for f, _exc in logged], [fname])
        self.assertIsInstance(logged[0][1], ValueError)
        self.assertIn(ftype, str(logged[0][1].args[0]))

    def test_nested_selection_skip_uses_full_path(self):
        """IFLD-C2: ``import_skip_records`` / ``import_set_empty_fields`` for a
        nested selection must match the full slash-path (``child_ids/type``),
        consistent with ``db_id_for`` and the paths the import UI emits."""
        fld = self.env["res.partner"]._fields["type"]
        # nested one level under a one2many named 'child_ids'
        nested = self.converter.with_context(
            parent_fields_hierarchy=["child_ids"],
            import_skip_records=["child_ids/type"],
        )
        value, warnings = nested._str_to_selection(fld, "not_a_real_type")
        self.assertIsNone(value)
        self.assertFalse(warnings)

        # a bare field name must NOT match a nested column (was the bug)
        bare = self.converter.with_context(
            parent_fields_hierarchy=["child_ids"],
            import_skip_records=["type"],
        )
        with self.assertRaises(ValueError):
            bare._str_to_selection(fld, "not_a_real_type")

    def test_str_to_selection_description_built_once(self):
        """IFLD-P2: a callable selection resolves without re-running the
        selection callable once per candidate item (was O(items^2))."""
        fld = self.env["ir.actions.server"]._fields["update_field_type"]
        self.assertTrue(callable(fld.selection), "need a callable selection")
        calls = []
        orig = type(fld)._description_selection

        def spy(self, env, *args, **kwargs):
            calls.append(1)
            return orig(self, env, *args, **kwargs)

        with patch.object(type(fld), "_description_selection", spy):
            # a value that never matches forces a full scan of the selection
            with self.assertRaises(ValueError):
                self.converter._str_to_selection(fld, "zzz_nonexistent_value")
        # Old code called this once per selection item (42x for a 19-item
        # selection). The fix makes it a small constant, independent of size.
        self.assertLessEqual(
            len(calls),
            5,
            "selection description must be built a constant number of times, "
            "not once per selection item",
        )

    def test_str_to_selection_index_single_query(self):
        """IFLD-P3: selection resolution builds one memoized reverse index per
        cursor, not one SQL query per selection item. Resolving every item of a
        ~600-value selection must stay a small constant number of queries."""
        fld = self.env["res.partner"]._fields["tz"]
        n = len(fld.selection)
        self.assertGreater(n, 100, "need a large static selection")
        # isolate from any index cached by an earlier test on this cursor, and
        # flush pending writes so only the index-build query runs under the spy
        self.env.cr.cache.get("ir.fields.converter", {}).pop(
            ("import_selection_index", fld.model_name, fld.name, self.env.lang), None
        )
        self.env["ir.model.fields.selection"].flush_model()

        cr = self.env.cr
        calls = []
        orig = cr.execute

        def spy(query, params=None):
            calls.append(1)
            return orig(query, params) if params is not None else orig(query)

        # Resolve every one of the ~600 items (valid values only, so the count
        # reflects the index, not incidental error-path translation loading).
        with patch.object(cr, "execute", spy):
            for item, _label in fld.selection:
                self.assertEqual(
                    self.converter._str_to_selection(fld, str(item))[0], item
                )
        self.assertLessEqual(
            len(calls),
            2,
            f"resolving all {n} items must build one whole-field index, not "
            f"issue a query per item (got {len(calls)} queries)",
        )

    def test_db_id_for_non_str_reference_is_clean_error(self):
        """IFLD-14: a non-string reference into an ``id`` / ``.id`` subfield
        yields a clean ValueError, never a raw TypeError/AttributeError that
        would escape ``db_id_for`` and abort ``load()``."""
        for subfield in (".id", "id"):
            with self.assertRaises(ValueError):
                self.converter.db_id_for(self.flds["m2o"], subfield, 123456789)

    def test_referencing_subfield_empty_record(self):
        """IFLD-C3: an empty reference record raises a clean, translatable
        ValueError rather than a raw 'not enough values to unpack'."""
        with self.assertRaises(ValueError) as cm:
            self.converter._referencing_subfield({})
        self.assertNotIn("unpack", str(cm.exception))

    def test_o2m_unknown_subfield_is_valueerror(self):
        """IFLD-15: a one2many sub-row with a field name absent from the comodel
        surfaces as ``ValueError`` (turned into a per-field error by
        ``for_model``), not a raw ``KeyError`` that aborts ``load()``."""
        fld = self.env["res.partner"]._fields["child_ids"]
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_one2many(fld, [{"bogus.x": "42"}])
        # the raw sub-field name is used as fallback in the error path
        self.assertIn("bogus.x", str(cm.exception.args[0]))

    def test_load_o2m_unknown_subfield_logs_not_crash(self):
        """IFLD-15 (end to end): loading an o2m sub-column whose name slips past
        ``_extract_records`` validation must produce a per-field import message
        on the o2m column, not abort ``load()`` with a ``KeyError``."""
        result = self.env["res.partner"].load(
            ["name", "child_ids/name", "child_ids/bogus.x"],
            [["IFLD15 Parent", "IFLD15 Child", "42"]],
        )
        self.assertFalse(result["ids"], "the erroneous import must not create ids")
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "expected a per-field import error message")
        self.assertEqual(errors[0].get("field"), "child_ids")
        self.assertIn("bogus.x", errors[0]["message"])

    def test_name_create_programming_error_propagates(self):
        """IFLD-16: a programming error raised by a ``name_create`` override
        must propagate, not be swallowed into the "cannot create from name
        alone" import message that masks the bug."""
        converter = self.converter.with_context(
            name_create_enabled_fields={"parent_id": True}
        )
        PartnerClass = type(self.env["res.partner"])
        with (
            patch.object(
                PartnerClass, "name_create", side_effect=TypeError("broken override")
            ),
            self.assertRaises(TypeError),
        ):
            converter.db_id_for(self.flds["m2o"], None, "zzz no such partner ifld16")

    def test_name_create_user_error_becomes_import_message(self):
        """IFLD-16 guard: a recoverable ``UserError`` from ``name_create``
        still resolves to the friendly "cannot create from name alone" import
        error."""
        converter = self.converter.with_context(
            name_create_enabled_fields={"parent_id": True}
        )
        PartnerClass = type(self.env["res.partner"])
        with (
            patch.object(PartnerClass, "name_create", side_effect=UserError("nope")),
            self.assertRaises(ValueError) as cm,
        ):
            converter.db_id_for(self.flds["m2o"], None, "zzz no such partner ifld16")
        self.assertIn("Cannot create new", str(cm.exception.args[0]))


@tagged("post_install", "-at_install")
class TestImportFiles(TransactionCase):
    @unittest.skipUnless(
        can_import("openpyxl"),
        "openpyxl not available",
    )
    def test_import_contacts_template_xls(self):
        if not loaded_demo_data(self.env):
            self.skipTest("Needs demo data to be able to import those files")
        model = "res.partner"
        filename = "contacts_import_template.xlsx"

        file_content = file_open(f"base/static/xls/{filename}", "rb").read()
        import_wizard = self.env["base_import.import"].create(
            {
                "res_model": model,
                "file": file_content,
                "file_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        )

        result = import_wizard.parse_preview(
            {
                "has_headers": True,
            },
        )
        self.assertIsNone(result.get("error"))
        field_names = ["/".join(v) for v in result["matches"].values()]
        results = import_wizard.execute_import(
            field_names,
            [r.lower() for r in result["headers"]],
            {
                "import_skip_records": [],
                "import_set_empty_fields": [],
                "fallback_values": {},
                "name_create_enabled_fields": {},
                "encoding": "",
                "separator": "",
                "quoting": '"',
                "date_format": "",
                "datetime_format": "",
                "float_thousand_separator": ",",
                "float_decimal_separator": ".",
                "advanced": True,
                "has_headers": True,
                "keep_matches": False,
                "limit": 2000,
                "skip": 0,
                "tracking_disable": True,
            },
        )
        self.assertFalse(
            results["messages"],
            "results should be empty on successful import of ",
        )
