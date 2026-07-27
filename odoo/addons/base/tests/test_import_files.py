import contextlib
import json
import unittest
from unittest.mock import patch

import psycopg

from odoo import Command
from odoo.exceptions import UserError
from odoo.libs.lru import LRU
from odoo.tests import TransactionCase, can_import, loaded_demo_data, tagged
from odoo.tools.misc import file_open


@tagged("post_install", "-at_install")
class TestFieldConverters(TransactionCase):
    """Unit coverage for ``ir.fields.converter`` ``_str_to_*`` methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.converter = cls.env["ir.fields.converter"]
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
        for value in ("2012-12-31xxx", "2012-12-31 nope"):
            with self.assertRaises(ValueError):
                self.converter._str_to_date(self.flds["date"], value)

    def test_boolean_value_sets_built_once(self):
        """IFLD-09: true/false token sets are memoized per cursor, not rebuilt
        per boolean cell.

        The rejected cells are caught with a bare ``except``, not
        ``assertRaises``: the latter runs ``traceback.clear_frames()``, which
        drops the traceback's frame locals and, through the resulting collection,
        reaches ``Transaction.clear()`` -- which empties ``cr.cache`` and so the
        memo under test. ``for_model`` catches converter errors with a plain
        ``except ValueError``, so this measures the path the import actually
        takes."""
        self.converter._import_memo().clear()
        calls = []
        orig = type(self.converter)._get_boolean_translations

        def spy(this, src):
            calls.append(src)
            return orig(this, src)

        with patch.object(type(self.converter), "_get_boolean_translations", spy):
            for _ in range(50):
                with contextlib.suppress(ValueError):
                    self.converter._str_to_boolean(self.flds["bool"], "maybe")
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
        empty, _w = self.converter.db_id_for(self.flds["m2o"], ".id", "0")
        self.assertIs(empty, False)
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

    def test_str_to_boolean_unknown_raises(self):
        """IFLD-03: an unknown boolean raises (never silently becomes ``True``).

        It used to return ``None`` plus an error smuggled through the warnings
        list, overloading the ``None`` that means "skip this record"."""
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_boolean(self.flds["bool"], "maybe")
        self.assertIn("maybe", str(cm.exception.args[0]))

    def test_str_to_boolean_skip_policy_still_returns_none(self):
        """IFLD-03 guard: ``None`` survives as the record-skip sentinel, and
        only for a field the policy actually covers."""
        skipping = self.converter.with_context(
            import_file=True, import_skip_records=["is_company"]
        )
        value, warnings = skipping._str_to_boolean(self.flds["bool"], "maybe")
        self.assertIsNone(value)
        self.assertFalse(warnings)

    def test_boolean_error_carries_field_path(self):
        """IFLD-03: a boolean error is decorated like every other converter
        error. Routing it through the warnings list bypassed ``for_model``'s
        ``except ValueError`` arm, so it was the one field type reaching the
        client with no ``field_path`` to highlight."""
        result = (
            self.env["res.partner"]
            .with_context(import_file=True)
            .load(["name", "is_company"], [["IFLD03 P", "maybe"]])
        )
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors)
        self.assertEqual(errors[0].get("field_path"), ["is_company"])
        self.assertEqual(errors[0].get("moreinfo"), "Use '1' for yes and '0' for no")

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
        result = fn({fname: "x"}, lambda field, exc: logged.append((field, exc)))
        self.assertNotIn(fname, result, "unconvertible field must not be written")
        self.assertEqual([f for f, _exc in logged], [fname])
        self.assertIsInstance(logged[0][1], ValueError)
        self.assertIn(ftype, str(logged[0][1].args[0]))

    def test_nested_selection_skip_uses_full_path(self):
        """IFLD-C2: ``import_skip_records`` / ``import_set_empty_fields`` for a
        nested selection must match the full slash-path (``child_ids/type``),
        consistent with ``db_id_for`` and the paths the import UI emits.

        ``import_file`` is part of the policy's precondition, so the contexts
        here carry it exactly as ``base_import`` builds them."""
        fld = self.env["res.partner"]._fields["type"]
        nested = self.converter.with_context(
            import_file=True,
            parent_fields_hierarchy=["child_ids"],
            import_skip_records=["child_ids/type"],
        )
        value, warnings = nested._str_to_selection(fld, "not_a_real_type")
        self.assertIsNone(value)
        self.assertFalse(warnings)

        bare = self.converter.with_context(
            import_file=True,
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
            with self.assertRaises(ValueError):
                self.converter._str_to_selection(fld, "zzz_nonexistent_value")
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
        self.converter._import_memo().clear()
        self.env["ir.model.fields.selection"].flush_model()

        cr = self.env.cr
        calls = []
        orig = cr.execute

        def spy(query, params=None):
            calls.append(1)
            return orig(query, params) if params is not None else orig(query)

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

    def test_m2m_blank_comma_segments_dropped(self):
        """IFLD-17: a trailing / leading / doubled comma in a many2many cell is
        not a reference. Resolving it to ``False`` used to leak into
        ``Command.set``, which fails at write time with a raw column type
        error."""
        tag = self.env["res.partner.category"].create({"name": "IFLD17 Tag"})
        converter = self.converter.to_field(
            self.env["res.partner"]._fields["category_id"], str
        )
        for raw in ("IFLD17 Tag,", ",IFLD17 Tag", "IFLD17 Tag, ", "IFLD17 Tag,,"):
            commands, warnings = converter([{None: raw}])
            self.assertFalse(warnings)
            self.assertEqual(
                commands,
                [Command.set([tag.id])],
                f"{raw!r} must resolve to exactly one reference",
            )

    def test_load_m2m_trailing_comma_imports(self):
        """IFLD-17 (end to end): a many2many column with a trailing comma must
        import cleanly instead of failing the record with a PostgreSQL
        "column is of type integer but expression is of type boolean" error."""
        self.env["res.partner.category"].create({"name": "IFLD17 E2E"})
        result = self.env["res.partner"].load(
            ["name", "category_id"], [["IFLD17 Partner", "IFLD17 E2E,"]]
        )
        self.assertFalse(result["messages"])
        self.assertTrue(result["ids"])
        partner = self.env["res.partner"].browse(result["ids"])
        self.assertEqual(partner.category_id.mapped("name"), ["IFLD17 E2E"])

    def test_o2m_blank_comma_segment_creates_no_record(self):
        """IFLD-18: a trailing comma in a one2many reference cell must not emit
        a ``Command.create({})`` that silently inserts a blank child record."""
        child = self.env["res.partner"].create({"name": "IFLD18 Child"})
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "ifld18_child",
                "model": "res.partner",
                "res_id": child.id,
            }
        )
        commands, warnings = self.converter._str_to_one2many(
            self.env["res.partner"]._fields["child_ids"],
            [{"id": "base.ifld18_child,"}],
        )
        self.assertFalse(warnings)
        self.assertEqual(commands, [Command.link(child.id)])

    def test_o2m_link_omits_empty_update(self):
        """IFLD-18: linking an existing one2many row with no writable values
        must not append a no-op ``Command.update(id, {})`` (a pointless UPDATE
        per imported row)."""
        child = self.env["res.partner"].create({"name": "IFLD18b Child"})
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "ifld18b_child",
                "model": "res.partner",
                "res_id": child.id,
            }
        )
        commands, _warnings = self.converter._str_to_one2many(
            self.env["res.partner"]._fields["child_ids"],
            [{"id": "base.ifld18b_child"}],
        )
        self.assertNotIn(
            Command.update(child.id, {}),
            commands,
            "an empty update command must not be emitted",
        )

    def test_non_str_error_param_survives_second_format_pass(self):
        """IFLD-19: import messages are ``%``-formatted twice (here, then in
        ``_convert_records``). A ``%`` inside a non-string error parameter used
        to reach the second pass unescaped and abort the whole import with a
        ``TypeError``."""
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_properties(
                self.flds["bool"], [{"name": "x", "string": "100% off"}]
            )
        message = str(cm.exception.args[0])
        formatted = message % {"record": 0, "field": "Props"}
        self.assertIn("100% off", formatted)

    def test_xmlid_model_mismatch_is_reportable_import_error(self):
        """IFLD-20: an external id pointing at another model reports a
        per-record import message. The message used to be a raw f-string, so a
        ``%`` in the external id crashed the second formatting pass and aborted
        the entire ``load()`` call."""
        lang = self.env["res.lang"].search([], limit=1)
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "ifld20_pct%x",
                "model": "res.lang",
                "res_id": lang.id,
            }
        )
        self.env.flush_all()
        result = self.env["res.partner"].load(
            ["name", "parent_id/id"], [["IFLD20", "base.ifld20_pct%x"]]
        )
        self.assertFalse(result["ids"])
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "expected a per-record import error message")
        self.assertIn("base.ifld20_pct%x", errors[0]["message"])
        self.assertIn("res.lang", errors[0]["message"])

    def test_driver_error_text_with_percent_is_escaped(self):
        """IFLD-21: a driver/codec exception message is user data too. Passing
        ``str(e)`` through unescaped broke the second formatting pass whenever
        the driver quoted a value containing ``%``."""
        converter = self.converter

        def boom(_value):
            raise psycopg.DataError('invalid input syntax for integer: "50%"')

        messages = []
        with patch.object(type(converter), "to_field", lambda *a, **kw: boom):
            convert = converter.for_model(self.env["res.partner"])
            convert({"name": "x"}, lambda f, e: messages.append(str(e.args[0])))

        self.assertTrue(messages, "expected the driver error to be logged")
        formatted = messages[0] % {"record": 0, "field": "Name"}
        self.assertIn('"50%"', formatted)

    def test_unknown_field_reported_and_not_written(self):
        """IFLD-22: an unknown field name is reported as a missing field and
        must not land in the converted values. A falsy value used to short
        circuit before the field-existence check, leaking the key into
        ``write()`` as ``False`` and raising a raw "Invalid field" ORM error."""
        convert = self.converter.for_model(self.env["res.partner"])
        logged = []
        converted = convert(
            {"name": "x", "ifld22_empty": "", "ifld22_filled": "v"},
            lambda f, e: logged.append((f, str(e.args[0]))),
        )
        self.assertEqual(converted, {"name": "x"})
        self.assertEqual(
            sorted(f for f, _m in logged), ["ifld22_empty", "ifld22_filled"]
        )
        for _field, message in logged:
            self.assertIn("does not exist", message)

    def test_relational_property_policy_path_matches_column(self):
        """IFLD-24: a relational Properties sub-value must resolve its import
        policy under the column path ``<field>.<property>`` (the name
        ``_extract_records`` splits on). Keying it off the property's display
        label meant ``import_skip_records`` / ``name_create_enabled_fields``
        never matched a many2one/many2many property."""
        captured = []

        def spy(this, field, record, *, multi):
            captured.append(field.name)
            return [], []

        with patch.object(type(self.converter), "_resolve_reference_ids", spy):
            self.converter._str_to_properties(
                self.flds["bool"],
                [
                    {
                        "name": "my_prop",
                        "type": "many2many",
                        "string": "My Display Label",
                        "comodel": "res.partner",
                        "value": [{None: "whatever"}],
                    }
                ],
            )
        self.assertEqual(captured, ["is_company.my_prop"])

    def test_selection_translation_index_is_ordered(self):
        """IFLD-23: the selection label index keeps the first token on a
        collision (``setdefault``), so the translation query must be ordered.
        Without ``ORDER BY`` the winner depended on PostgreSQL row order."""
        field = self.env["res.partner"]._fields["type"]
        self.converter._import_memo().clear()
        queries = []
        orig_execute = type(self.env.cr).execute

        def spy(cr, query, *args, **kwargs):
            queries.append(str(query))
            return orig_execute(cr, query, *args, **kwargs)

        with patch.object(type(self.env.cr), "execute", spy):
            self.converter._selection_import_index(field)
        selection_queries = [q for q in queries if "ir_model_fields_selection" in q]
        self.assertTrue(selection_queries, "expected the selection label query")
        self.assertTrue(
            any("ORDER BY" in q.upper() for q in selection_queries),
            "the selection label query must be deterministically ordered",
        )

    def test_load_unknown_column_reports_instead_of_crashing(self):
        """IFLD-25: an unknown import column must produce a per-field message.

        A dotted name slipped past ``_extract_records`` and reached ``_log``,
        which looked its label up with ``field_names[field]`` and raised a raw
        ``KeyError`` out of ``load()``; a plain name raised ``Invalid field
        name`` there. Either way the caller got an exception instead of the
        documented ``{ids, messages}``, and ``load()``'s savepoint was left
        open, so the next ``cr.rollback()`` failed too."""
        for column in ("bogus.x", "nosuchfield"):
            with self.subTest(column=column):
                result = self.env["res.partner"].load(
                    ["name", column], [["IFLD25", "42"]]
                )
                self.assertFalse(result["ids"])
                errors = [m for m in result["messages"] if m.get("type") == "error"]
                self.assertTrue(errors, "expected a per-field import error")
                self.assertEqual(errors[0].get("field"), column)
                self.assertIn("does not exist", errors[0]["message"])
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone(), (1,))

    def test_skip_records_ignores_columns_absent_from_the_import(self):
        """IFLD-26: ``import_skip_records`` naming a field that is not one of
        this import's columns must not drop anything.

        The check was ``record.get(path) is None``, so an absent key matched on
        *every* record: the whole import was silently discarded and reported no
        message at all."""
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["type"]
        )
        result = model.load(["name"], [["IFLD26 A"], ["IFLD26 B"]])
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"] or []), 2, "no record may be skipped")

    def test_skip_records_still_skips_the_unresolved_record(self):
        """IFLD-26 guard: a listed top-level field whose cell does not resolve
        still skips just that record."""
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["type"]
        )
        result = model.load(
            ["name", "type"],
            [["IFLD26 bad", "not_a_real_type"], ["IFLD26 ok", "contact"]],
        )
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"] or []), 1, "only the bad row is skipped")

    def test_nested_skip_records_skips_the_parent_record(self):
        """IFLD-27: ``import_skip_records`` on a nested field (``child_ids/type``)
        must skip the record.

        The converter's ``None`` sentinel stayed buried in the one2many payload
        where ``load()``'s top-level check could never see it, so the record was
        imported with the unresolved value instead of being skipped."""
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["child_ids/type"]
        )
        result = model.load(
            ["name", "child_ids/name", "child_ids/type"],
            [["IFLD27 Parent", "IFLD27 Child", "not_a_real_type"]],
        )
        self.assertFalse(result["messages"])
        self.assertFalse(result["ids"], "the record must be skipped")
        self.assertFalse(
            self.env["res.partner"].search([("name", "=", "IFLD27 Parent")])
        )

    def test_nested_skip_records_keeps_resolvable_records(self):
        """IFLD-27 guard: with the same policy, a row whose nested cell *does*
        resolve must still import."""
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["child_ids/type"]
        )
        result = model.load(
            ["name", "child_ids/name", "child_ids/type"],
            [["IFLD27 Good", "IFLD27 Good Child", "contact"]],
        )
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"] or []), 1)

    def test_name_create_driver_error_leaves_cursor_usable(self):
        """IFLD-28: a ``name_create`` that fails with a driver error aborts the
        PostgreSQL transaction. It is now contained in its own savepoint.

        Before, the rollback was the caller's whole-import savepoint, taken from
        the ``import_savepoint`` context key -- absent for any direct caller of
        ``db_id_for``, which was then handed the friendly "cannot create from
        name alone" message on a dead cursor, turning every later statement into
        ``InFailedSqlTransaction``."""
        converter = self.converter.with_context(
            name_create_enabled_fields={"parent_id": True}
        )

        def boom(*args, **kwargs):
            self.env.cr.execute("SELECT 1 / 0")

        PartnerClass = type(self.env["res.partner"])
        with patch.object(PartnerClass, "name_create", side_effect=boom):
            with self.assertRaises(ValueError) as cm:
                converter.db_id_for(
                    self.flds["m2o"], None, "zzz no such partner ifld28"
                )
        self.assertIn("Cannot create new", str(cm.exception.args[0]))
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone(), (1,))

    def test_repeated_references_resolved_once_per_import(self):
        """IFLD-29: identical references must be resolved once per ``load()``.

        ``name_search`` ran per cell, so 100 rows pointing at one parent issued
        1308 queries; only the external-id path was memoized."""
        parent = self.env["res.partner"].create({"name": "IFLD29 Shared Parent"})
        self.env.flush_all()
        PartnerClass = type(self.env["res.partner"])
        calls = []
        orig = PartnerClass.name_search

        def spy(this, *args, **kwargs):
            calls.append(kwargs.get("name"))
            return orig(this, *args, **kwargs)

        rows = [[f"IFLD29 c{i}", "IFLD29 Shared Parent"] for i in range(6)]
        with patch.object(PartnerClass, "name_search", spy):
            result = self.env["res.partner"].load(["name", "parent_id"], rows)
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"] or []), 6)
        self.assertEqual(
            len(calls), 1, f"6 identical references must search once, got {len(calls)}"
        )
        self.assertEqual(
            self.env["res.partner"].browse(result["ids"]).mapped("parent_id"), parent
        )

    def test_reference_miss_is_not_cached(self):
        """IFLD-29 guard: only successful lookups may be memoized. A reference
        that misses can be satisfied by a record created later in the same
        import, so caching the miss would let row order decide the outcome.

        Driven through ``db_id_for`` directly with a record created between the
        two lookups: an end-to-end ``load()`` cannot distinguish the two
        implementations, because a miss that is never re-queried also never
        reveals that it was cached."""
        converter = self.converter.with_context(
            import_file=True,
            import_set_empty_fields=["parent_id"],
            import_cache=LRU(1024),
        )
        first, _w = converter.db_id_for(self.flds["m2o"], None, "IFLD29b Target")
        self.assertIsNone(first, "the record does not exist yet")
        target = self.env["res.partner"].create({"name": "IFLD29b Target"})
        self.env.flush_all()
        second, _w = converter.db_id_for(self.flds["m2o"], None, "IFLD29b Target")
        self.assertEqual(
            second, target.id, "a cached miss would still report 'not found'"
        )

    def test_reference_cache_does_not_outlive_one_load(self):
        """IFLD-29 guard: the memo lives in the per-``load()`` ``import_cache``,
        so a reference resolved by one import is re-resolved by the next."""
        target = self.env["res.partner"].create({"name": "IFLD29c Target"})
        self.env.flush_all()
        first = self.env["res.partner"].load(
            ["name", "parent_id"], [["IFLD29c child", "IFLD29c Target"]]
        )
        self.assertFalse(first["messages"])
        self.env["res.partner"].browse(first["ids"]).unlink()
        target.unlink()
        self.env.flush_all()
        second = self.env["res.partner"].load(
            ["name", "parent_id"], [["IFLD29c child2", "IFLD29c Target"]]
        )
        self.assertFalse(second["ids"], "the deleted target must not resolve")
        self.assertTrue(
            [m for m in second["messages"] if m.get("type") == "error"],
            "expected a 'no matching record' error",
        )

    def test_nested_skip_policy_requires_import_file(self):
        """IFLD-27 guard: ``import_skip_records`` without ``import_file`` is not
        in force, so an unresolvable cell is an ordinary reported error.

        ``ir.fields.converter`` and ``load()`` have to agree on when the policy
        applies. While only the converter honoured it, the one2many propagated
        its ``None`` upward, ``load()`` declined to skip the record, and the
        ``None`` was written -- silently dropping the child. Both of the wrong
        behaviours are silent, so what pins this down is that a message is
        reported at all."""
        model = self.env["res.partner"].with_context(
            import_skip_records=["child_ids/type"]
        )
        result = model.load(
            ["name", "child_ids/name", "child_ids/type"],
            [["IFLD27b Parent", "IFLD27b Child", "not_a_real_type"]],
        )
        self.assertFalse(result["ids"])
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "the bad cell must be reported, not skipped")
        self.assertEqual(errors[0].get("field_path"), ["child_ids", "type"])

    def test_nested_o2m_without_policy_still_creates_the_child(self):
        """IFLD-27 guard: with no policy in force and a resolvable nested cell,
        the one2many must convert normally -- the skip sentinel must never be
        propagated spuriously."""
        model = self.env["res.partner"].with_context(
            import_skip_records=["child_ids/type"]
        )
        result = model.load(
            ["name", "child_ids/name", "child_ids/type"],
            [["IFLD27d Parent", "IFLD27d Child", "contact"]],
        )
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"] or []), 1)
        parent = self.env["res.partner"].browse(result["ids"])
        self.assertEqual(parent.child_ids.mapped("name"), ["IFLD27d Child"])

    def test_deeply_nested_skip_records_propagates(self):
        """IFLD-27: a skip policy two one2many levels down still skips the
        record -- each level folds the deeper path onto its own field and
        propagates the sentinel upward in turn."""
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["child_ids/child_ids/type"]
        )
        result = model.load(
            [
                "name",
                "child_ids/name",
                "child_ids/child_ids/name",
                "child_ids/child_ids/type",
            ],
            [["IFLD27c P", "IFLD27c C", "IFLD27c GC", "not_a_real_type"]],
        )
        self.assertFalse(result["messages"])
        self.assertFalse(result["ids"], "the record must be skipped")
        self.assertFalse(self.env["res.partner"].search([("name", "=", "IFLD27c P")]))

    def test_many2one_multiple_reference_records_clean_error(self):
        """IFLD-30: a malformed many2one payload must not surface Python's
        "too many values to unpack (expected 1, got 2)" as the import message."""
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_many2one(
                self.flds["m2o"], [{None: "a"}, {None: "b"}]
            )
        self.assertNotIn("unpack", str(cm.exception.args[0]))
        self.assertIn("single reference", str(cm.exception.args[0]))

    def test_error_field_path_does_not_invent_property_subfields(self):
        """IFLD-31: the error path for a Properties value must name the column,
        not its ``name`` metadata key. The old walk into the first key of the
        first sub-dict reported ``['props', 'name']`` as the failing field."""
        properties_value = [
            {"name": "p1", "type": "integer", "string": "P1", "value": "x"}
        ]
        self.assertEqual(
            self.converter._error_field_path("props", properties_value), ["props"]
        )

    def test_error_field_path_keeps_the_referencing_subfield(self):
        """IFLD-31 guard: a relational value is still attributed to the
        sub-field it was addressed by, so ``value/id`` reports
        ``['value', 'id']`` and a bare name reports just ``['value']``."""
        self.assertEqual(
            self.converter._error_field_path("value", [{"id": "noxidhere"}]),
            ["value", "id"],
        )
        self.assertEqual(
            self.converter._error_field_path("value", [{None: "somename"}]), ["value"]
        )
        nested = self.converter.with_context(parent_fields_hierarchy=["child_ids"])
        self.assertEqual(nested._error_field_path("type", "bad"), ["child_ids", "type"])

    def test_o2m_subfield_label_with_percent_is_reported(self):
        """IFLD-32: a one2many sub-field whose *label* contains a ``%`` must
        still report a per-record message.

        The label is spliced into the message's ``%(field)s`` slot before
        ``_convert_records`` runs its own ``%``-formatting pass, so an unescaped
        one blew that pass up with a ``TypeError`` -- raised outside every
        converter's reach, aborting the whole ``load()``. Real labels carry
        ``%`` routinely (``order_line/discount`` is "Discount (%)")."""
        fld = self.env["res.partner"]._fields["type"]
        with patch.object(fld, "string", "Address Type (%)"):
            result = (
                self.env["res.partner"]
                .with_context(import_file=True)
                .load(
                    ["name", "child_ids/name", "child_ids/type"],
                    [["IFLD32 Parent", "IFLD32 Child", "not_a_real_type"]],
                )
            )
        self.assertFalse(result["ids"])
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "expected a per-record import error message")
        self.assertIn("Address Type (%)", errors[0]["message"])
        self.assertEqual(errors[0].get("field_path"), ["child_ids", "type"])

    def test_o2m_unknown_subfield_with_percent_is_reported(self):
        """IFLD-32 guard: the same holds for the fallback label, the raw column
        name, used when the sub-field does not exist on the comodel."""
        result = self.env["res.partner"].load(
            ["name", "child_ids/name", "child_ids/bogus%x"],
            [["IFLD32b Parent", "IFLD32b Child", "42"]],
        )
        self.assertFalse(result["ids"])
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "expected a per-field import error message")
        self.assertIn("bogus%x", errors[0]["message"])

    def test_property_missing_type_metadata_is_reported(self):
        """IFLD-33: a Properties payload whose entry lacks the metadata its type
        needs must raise a reportable ``ValueError``.

        The coercion arms read ``selection`` / ``tags`` / ``comodel`` straight
        out of what is user data (a Properties column may hold the whole field
        as a JSON string), so a missing key surfaced as a bare ``KeyError`` --
        which ``for_model`` does not catch, aborting the entire ``load()``."""
        for ptype, missing in (
            ("selection", "selection"),
            ("tags", "tags"),
            ("many2one", "comodel"),
            ("many2many", "comodel"),
        ):
            with self.subTest(type=ptype):
                with self.assertRaises(ValueError) as cm:
                    self.converter._str_to_properties(
                        self.flds["bool"],
                        [
                            {
                                "name": "p",
                                "type": ptype,
                                "string": "P",
                                "value": "whatever",
                            }
                        ],
                    )
                self.assertIn(missing, str(cm.exception.args[0]))

    def test_boolean_property_policy_path_matches_column(self):
        """IFLD-34: a boolean Properties sub-value must resolve its import
        policy under the column path ``<field>.<property>``, like the relational
        ones (IFLD-24). Keyed off the parent Properties field, "Skip record"
        chosen on a property column never applied, and the option offered on the
        parent applied to every property at once.

        The sentinel is the *whole field's* value, not a ``None`` parked inside
        the payload: that payload is a non-empty list, so it is never ``None``
        itself and the record-level check in ``load()`` could not see it
        (IFLD-46)."""
        payload = [
            {"name": "mybool", "type": "boolean", "string": "My Bool", "value": "maybe"}
        ]
        column = self.converter.with_context(
            import_file=True, import_skip_records=["is_company.mybool"]
        )
        value, warnings = column._str_to_properties(self.flds["bool"], payload)
        self.assertIsNone(value, "the skip sentinel must propagate")
        self.assertFalse(warnings)

        parent = self.converter.with_context(
            import_file=True, import_skip_records=["is_company"]
        )
        with self.assertRaises(ValueError):
            parent._str_to_properties(self.flds["bool"], payload)

    def test_xmlid_model_mismatch_does_not_depend_on_id_overlap(self):
        """IFLD-35: an external id belonging to another model is reported as
        such whether or not the expected model happens to own a record with the
        same id.

        The existence check was an inner ``JOIN`` on ``d.res_id = r.id`` with
        nothing constraining ``d.model``, so a foreign xmlid was only diagnosed
        when some unrelated record collided on the id, and otherwise reported
        the same "no matching record found" a plain typo gives."""
        self.env.cr.execute("SELECT COALESCE(max(id), 0) + 1000 FROM res_partner")
        [free_id] = self.env.cr.fetchone()
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "ifld35_elsewhere",
                "model": "res.lang",
                "res_id": free_id,
            }
        )
        self.env.flush_all()
        result = self.env["res.partner"].load(
            ["name", "parent_id/id"], [["IFLD35", "base.ifld35_elsewhere"]]
        )
        self.assertFalse(result["ids"])
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors)
        self.assertIn("res.lang", errors[0]["message"])
        self.assertNotIn("No matching record", errors[0]["message"])

    def test_name_create_enabled_uses_the_full_field_path(self):
        """IFLD-36: ``name_create_enabled_fields`` is keyed by the import UI's
        field paths (``child_ids/parent_id``), like the two policy lists, and is
        resolved through the same ``_import_policy_path``."""
        result = (
            self.env["res.partner"]
            .with_context(
                import_file=True,
                name_create_enabled_fields={"child_ids/parent_id": True},
            )
            .load(
                ["name", "child_ids/name", "child_ids/parent_id"],
                [["IFLD36 Parent", "IFLD36 Child", "IFLD36 Created By Name"]],
            )
        )
        self.assertFalse(result["messages"])
        self.assertTrue(result["ids"])
        created = self.env["res.partner"].search(
            [("name", "=", "IFLD36 Created By Name")]
        )
        self.assertTrue(created, "the nested reference must have been name_created")

    def test_import_policy_is_a_single_decision(self):
        """IFLD-37: every converter resolves the import options to one
        :class:`ImportPolicy`. They used to read an independent
        ``(skip, set_empty)`` pair and each invent its own precedence for the
        combination the UI cannot emit: a selection skipped the record while a
        many2many quietly emptied itself."""
        both = self.converter.with_context(
            import_file=True,
            import_skip_records=["type", "category_id", "parent_id"],
            import_set_empty_fields=["type", "category_id", "parent_id"],
        )
        partner_fields = self.env["res.partner"]._fields
        self.assertIsNone(both._str_to_selection(partner_fields["type"], "zzz")[0])
        self.assertIsNone(
            both._str_to_many2many(partner_fields["category_id"], [{None: "zzz"}])[0]
        )
        self.assertIsNone(
            both._str_to_many2one(partner_fields["parent_id"], [{None: "zzz"}])[0]
        )

    def test_non_text_reference_is_a_clean_error(self):
        """IFLD-38: a non-text reference must name the offending value's type,
        not reach ``for_model``'s catch-all as ``'int' object has no attribute
        'split'`` -- which reports the *enclosing list*'s type instead.

        Both splitting call sites are covered: ``_resolve_reference_ids`` for
        many2many, and ``_str_to_one2many``'s single-reference-cell branch,
        which calls ``_split_references`` directly. The guard therefore lives in
        ``_split_references``, the one place that requires text."""
        partner_fields = self.env["res.partner"]._fields
        converters = {
            "category_id": self.converter._str_to_many2many,
            "child_ids": self.converter._str_to_one2many,
        }
        for fname, convert in converters.items():
            for raw in (12345, ["a", "b"]):
                with self.subTest(field=fname, raw=raw):
                    with self.assertRaises(ValueError) as cm:
                        convert(partner_fields[fname], [{None: raw}])
                    self.assertIn(type(raw).__name__, str(cm.exception.args[0]))

    def test_name_create_enabled_does_not_leak_across_depths(self):
        """IFLD-36 guard: a ``name_create_enabled_fields`` key at one depth must
        not enable creation at another.

        This is what the prefix-stripping the refactor removed used to enforce
        structurally, by rebuilding a per-level dict; the full-path lookup has
        to keep enforcing it, or a top-level "Create new values" would silently
        start creating records for every same-named nested column."""
        result = (
            self.env["res.partner"]
            .with_context(
                import_file=True,
                name_create_enabled_fields={"parent_id": True},
            )
            .load(
                ["name", "child_ids/name", "child_ids/parent_id"],
                [["IFLD36b Parent", "IFLD36b Child", "IFLD36b Must Not Exist"]],
            )
        )
        errors = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(errors, "the nested reference must not resolve")
        self.assertFalse(
            self.env["res.partner"].search([("name", "=", "IFLD36b Must Not Exist")]),
            "a top-level name_create option must not apply to a nested column",
        )

    def test_nested_error_carries_its_own_field_path(self):
        """IFLD-31 guard: a one2many sub-field error still reports the deep path
        -- attached where the failing sub-field is actually known."""
        messages = []
        model = self.env["res.partner"].with_context(import_file=True)
        result = model.load(
            ["name", "child_ids/name", "child_ids/type"],
            [["IFLD31 Parent", "IFLD31 Child", "not_a_real_type"]],
        )
        messages = [m for m in result["messages"] if m.get("type") == "error"]
        self.assertTrue(messages)
        self.assertEqual(messages[0].get("field_path"), ["child_ids", "type"])

    def test_many2one_reference_is_stripped_like_many2many(self):
        """IFLD-39: whitespace around a reference is separator noise in a
        many2one cell exactly as it is in a many2many one.

        base_import strips only float and date cells, so " Foo " reached
        ``name_search`` verbatim and failed the record, while the same spelling
        in a many2many column resolved -- the two paths disagreeing about the
        same character.
        """
        partner = self.env["res.partner"].create({"name": "IFLD39 Parent"})
        tag = self.env["res.partner.category"].create({"name": "IFLD39 Tag"})
        fields = self.env["res.partner"]._fields
        for raw in (
            "IFLD39 Parent",
            " IFLD39 Parent",
            "IFLD39 Parent ",
            "\tIFLD39 Parent\n",
        ):
            with self.subTest(raw=raw):
                got, warnings = self.converter._str_to_many2one(
                    fields["parent_id"], [{None: raw}]
                )
                self.assertFalse(warnings)
                self.assertEqual(got, partner.id)
        commands, _w = self.converter._str_to_many2many(
            fields["category_id"], [{None: " IFLD39 Tag "}]
        )
        self.assertEqual(commands, [Command.set([tag.id])])

    def test_many2one_reference_accepts_a_raw_database_id(self):
        """IFLD-39 guard: stripping must not impose a text requirement on the
        single-reference path. ``load()`` is called with a record's ``int`` id
        for a ``.id`` sub-field, which needs no splitting and so no text."""
        partner = self.env["res.partner"].create({"name": "IFLD39b Partner"})
        got, warnings = self.converter._str_to_many2one(
            self.env["res.partner"]._fields["parent_id"], [{".id": partner.id}]
        )
        self.assertFalse(warnings)
        self.assertEqual(got, partner.id)

    def test_set_empty_many2one_is_false_not_the_skip_sentinel(self):
        """IFLD-40: ``None`` is the record-skip sentinel every converter shares,
        so "set value as empty" on a many2one must report ``False`` -- as the
        selection and many2many converters already do -- not ``db_id_for``'s
        bare ``None``."""
        fields = self.env["res.partner"]._fields
        converter = self.converter.with_context(
            import_file=True,
            import_set_empty_fields=["parent_id", "type"],
        )
        got, _w = converter._str_to_many2one(
            fields["parent_id"], [{None: "IFLD40 nope"}]
        )
        self.assertIs(got, False)
        self.assertIs(
            converter._str_to_selection(fields["type"], "IFLD40 nope")[0], False
        )

    def test_skip_record_many2one_still_returns_none(self):
        """IFLD-40 guard: the skip policy keeps the sentinel, so ``load()``
        still drops the record."""
        converter = self.converter.with_context(
            import_file=True, import_skip_records=["parent_id"]
        )
        got, _w = converter._str_to_many2one(
            self.env["res.partner"]._fields["parent_id"], [{None: "IFLD40b nope"}]
        )
        self.assertIsNone(got)

    def test_database_id_possible_values_shows_database_ids(self):
        """IFLD-41: both id sub-fields point at ``ir.model.data`` because its
        list view shows ``res_id`` -- the database id a ``.id`` cell needs, and
        which no comodel list view exposes by default. Retargeting ``.id`` at
        the comodel on the grounds that external ids are not valid ``.id``
        values drops the one column that answers the question."""
        field = self.env["res.partner"]._fields["parent_id"]
        for subfield in ("id", ".id"):
            action = self.converter._possible_values_action(field, subfield)
            self.assertEqual(action["res_model"], "ir.model.data")
            self.assertEqual(action["domain"], [("model", "=", "res.partner")])
        by_name = self.converter._possible_values_action(field, None)
        self.assertEqual(by_name["res_model"], "res.partner")

    def test_unparseable_datetime_is_reported_not_a_server_fault(self):
        """IFLD-42: a value holding no datetime must be reported like any other
        unparseable cell. ``fields.Datetime.from_string`` answers ``None`` for a
        falsy value, which reached ``.replace(tzinfo=...)`` as an
        ``AttributeError`` -- routed to ``for_model``'s catch-all, which logs a
        traceback at ERROR and tells the user to read the server logs."""
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_datetime(self.flds["dt"], "")
        self.assertIn("datetime", str(cm.exception.args[0]))

    def test_malformed_property_definition_is_reported(self):
        """IFLD-43: a Properties column may carry the whole field as JSON, so
        the definitions are user data too. Their shape must be validated where
        the presence of the keys already is, instead of surfacing as raw Python:
        "not enough values to unpack (expected 3, got 2)" for a short ``tags``
        row, or ``TypeError: unhashable`` for a non-text ``type``."""
        field = self.env["res.partner"]._fields["properties"]
        base = {"name": "p1", "string": "P1"}
        cases = {
            "short tags row": dict(base, type="tags", tags=[["a", "A"]], value="a"),
            "short selection row": dict(
                base, type="selection", selection=[["a"]], value="a"
            ),
            "non-text type": dict(base, type=["nonsense"], value=1),
        }
        for label, property_dict in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ValueError) as cm:
                    self.converter._str_to_properties(field, [property_dict])
                message = str(cm.exception.args[0])
                self.assertNotIn("unpack", message)
                self.assertNotIn("unhashable", message)

    def test_non_numeric_property_value_is_reported(self):
        """IFLD-43: a Properties sub-value is user data, so a JSON list or
        object reaches ``int()`` / ``float()`` as readily as a bad string does.
        Catching only ``ValueError`` sent that spelling to ``for_model``'s
        catch-all, which logs a traceback at ERROR per cell."""
        field = self.env["res.partner"]._fields["properties"]
        base = {"name": "p1", "string": "P1"}
        for property_type, value in (("integer", [1, 2]), ("float", {"a": 1})):
            with self.subTest(type=property_type):
                with self.assertRaises(ValueError) as cm:
                    self.converter._str_to_properties(
                        field, [dict(base, type=property_type, value=value)]
                    )
                self.assertIn("P1", str(cm.exception.args[0]))

    def _define_partner_properties(self, definition):
        """Install ``definition`` as res.partner's shared Properties definition."""
        record = (
            self.env["properties.base.definition"]
            .sudo()
            ._get_definition_for_property_field("res.partner", "properties")
        )
        record.properties_definition = definition
        self.env.cr.flush()
        self.env.registry.clear_cache()

    def test_unknown_property_comodel_does_not_abort_the_import(self):
        """IFLD-45: a relational property's ``comodel`` reaches ``self.env[...]``
        as a ``KeyError``, which ``for_model`` does not catch -- so one bad name
        in a pasted Properties JSON payload propagated out of ``load()`` and lost
        every row, not just its own.

        ``base_import`` drops relational property *columns* whose comodel is
        unknown, but the whole-field JSON column it does offer carries its own
        definitions, so the payload is user data all the way down."""
        blob = json.dumps(
            [
                {
                    "name": "p",
                    "type": "many2one",
                    "string": "P",
                    "comodel": "no.such.model",
                    "value": [{"id": "base.x"}],
                }
            ]
        )
        model = self.env["res.partner"].with_context(import_file=True)
        result = model.load(
            ["name", "properties"], [["IFLD45 Bad", blob], ["IFLD45 Good", ""]]
        )
        self.assertTrue(result["messages"], "the bad cell must be reported")
        self.assertIn(
            "no.such.model",
            " ".join(m.get("message", "") for m in result["messages"]),
        )

    def test_skip_record_on_a_property_column_skips_the_record(self):
        """IFLD-46: "Skip record" on a Properties column silently created the
        record with that property set to null.

        Two things kept the sentinel from arriving: ``_str_to_properties`` left
        the sub-value's ``None`` inside its payload -- a non-empty list, so never
        ``None`` itself -- and ``load()._import_skip_fields`` folded policy paths
        on ``/`` only, leaving the ``.``-separated Properties path unmatchable.
        """
        self._define_partner_properties(
            [{"name": "pb", "type": "boolean", "string": "PB"}]
        )
        model = self.env["res.partner"].with_context(
            import_file=True, import_skip_records=["properties.pb"]
        )
        self.assertEqual(model._import_skip_fields(), frozenset({"properties"}))
        result = model.load(["name", "properties.pb"], [["IFLD46 SkipMe", "maybe"]])
        self.assertFalse(result["ids"], "the record must be skipped, not created")
        self.assertFalse(
            self.env["res.partner"].search([("name", "=", "IFLD46 SkipMe")])
        )

    def test_set_empty_property_many2many_does_not_fail_the_import(self):
        """IFLD-47: an unresolved reference arrives as ``None`` and has to be
        spent by the Properties relational converter, exactly as the field
        converters spend it. Kept in the payload, the list reached the ORM as
        ``Wrong many2many value [42, None]`` -- a ``ValueError`` raised past
        every converter, failing the whole import rather than the one cell the
        policy was chosen for."""
        self._define_partner_properties(
            [
                {
                    "name": "pm",
                    "type": "many2many",
                    "string": "PM",
                    "comodel": "res.partner.category",
                }
            ]
        )
        tag = self.env["res.partner.category"].create({"name": "IFLD47 Tag"})
        model = self.env["res.partner"].with_context(
            import_file=True, import_set_empty_fields=["properties.pm"]
        )
        result = model.load(
            ["name", "properties.pm"], [["IFLD47 Mixed", "IFLD47 Tag,zzz nope zzz"]]
        )
        self.assertFalse(result["messages"])
        self.assertTrue(result["ids"])
        partner = self.env["res.partner"].browse(result["ids"][0])
        self.assertEqual(partner.properties["pm"].ids, [tag.id])

    def test_property_selection_obeys_the_import_policy(self):
        """IFLD-48: the import UI offers "Set value as empty" and "Skip record"
        on a property selection column exactly as it does on a selection field
        (``get_fields`` publishes the sub-column under the property's own type),
        but this arm consulted no policy at all, so both choices raised."""
        field = self.flds["bool"]
        payload = [
            {
                "name": "sel",
                "type": "selection",
                "string": "Sel",
                "selection": [["a", "A"]],
                "value": "nope",
            }
        ]
        empty = self.converter.with_context(
            import_file=True, import_set_empty_fields=["is_company.sel"]
        )
        self.assertIs(empty._str_to_properties(field, payload)[0][0]["value"], False)

        skip = self.converter.with_context(
            import_file=True, import_skip_records=["is_company.sel"]
        )
        self.assertIsNone(skip._str_to_properties(field, payload)[0])

        with self.assertRaises(ValueError):
            self.converter._str_to_properties(field, payload)

    def test_nested_converter_is_built_once_per_import(self):
        """IFLD-49: ``for_model`` exists to build each field's converter once per
        model, but a one2many rebuilt that whole table -- plus an ``Environment``
        fork for the hierarchy context -- for every *record*, so the cache never
        survived a row (401 ``for_model`` calls for 400 records)."""
        calls = []
        converter_type = type(self.converter)
        original = converter_type.for_model

        def spy(this, model, fromtype=str):
            calls.append(model._name)
            return original(this, model, fromtype)

        rows = [[f"IFLD49 P{i}", f"IFLD49 C{i}"] for i in range(25)]
        with patch.object(converter_type, "for_model", spy):
            result = self.env["res.partner"].load(["name", "child_ids/name"], rows)
        self.assertFalse(result["messages"])
        self.assertEqual(len(result["ids"]), 25)
        self.assertLessEqual(
            len(calls),
            4,
            "the one2many converter must be reused across records, not rebuilt "
            f"per row (built {len(calls)} times for {len(rows)} records)",
        )

    def test_one2many_payload_is_validated_like_the_others(self):
        """IFLD-44: the many2one / many2many converters validate their payload
        because ``load()`` is public; the one holding *many* did not, so a
        malformed payload surfaced as "'str' object has no attribute 'items'"
        -- naming the type of the enclosing list, not of the bad element."""
        with self.assertRaises(ValueError) as cm:
            self.converter._str_to_one2many(
                self.env["res.partner"]._fields["child_ids"], ["notadict"]
            )
        self.assertNotIn("has no attribute", str(cm.exception.args[0]))


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
