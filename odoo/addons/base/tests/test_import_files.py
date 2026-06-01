import unittest

from odoo.tests import TransactionCase, can_import, loaded_demo_data, tagged
from odoo.tools.misc import file_open


@tagged("post_install", "-at_install")
class TestFieldConverters(TransactionCase):
    """Unit coverage for ``ir.fields.converter`` ``_str_to_*`` methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.converter = cls.env["ir.fields.converter"]
        # The datetime/date/boolean converters only read ``field.name`` (boolean)
        # and never ``savepoint`` (passed as ``None``); any concrete field works.
        # Keep the Field objects in a dict, NOT as class attributes: a Field is a
        # data descriptor, so ``self.flds["dt"]`` would invoke ``Field.__get__`` on
        # the TestCase (not a recordset) and raise. Dict access avoids that.
        cls.flds = {
            "dt": cls.env["res.partner"]._fields["write_date"],
            "date": cls.env["res.partner"]._fields["write_date"],
            "bool": cls.env["res.partner"]._fields["is_company"],
        }

    def test_str_to_datetime_offset_bearing_iso_not_double_converted(self):
        """IFLD-01: an offset-bearing ISO string maps to the correct UTC instant.

        ``16:09:18-06:00`` is ``22:09:18`` UTC. With env.tz set to a non-UTC
        zone, the buggy double-application would have produced ``04:09:18`` the
        next day; the fix must keep the already-converted instant untouched.
        """
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.env["res.partner"],
            self.flds["dt"],
            "2026-03-19T16:09:18-06:00",
            None,
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2026-03-19 22:09:18")

    def test_str_to_datetime_naive_applies_input_tz(self):
        """IFLD-01 guard: the standard base_import (naive, offset-free) path
        still applies env.tz before storing as UTC."""
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.env["res.partner"],
            self.flds["dt"],
            "2026-03-19 16:09:18",
            None,
        )
        self.assertFalse(warnings)
        # 16:09:18 wall-clock at -06:00 == 22:09:18 UTC.
        self.assertEqual(value, "2026-03-19 22:09:18")

    def test_str_to_datetime_utc_z_suffix_not_double_converted(self):
        """IFLD-01: a ``Z`` (UTC) suffix is tz-aware and must not be re-stamped."""
        converter = self.converter.with_context(tz="America/Mexico_City")
        value, warnings = converter._str_to_datetime(
            self.env["res.partner"],
            self.flds["dt"],
            "2026-03-19T16:09:18Z",
            None,
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2026-03-19 16:09:18")

    def test_str_to_date_rejects_trailing_garbage(self):
        """IFLD-02: a date with trailing garbage must raise, not truncate."""
        with self.assertRaises(ValueError):
            self.converter._str_to_date(
                self.env["res.partner"],
                self.flds["date"],
                "2012-12-31xxx",
                None,
            )

    def test_str_to_date_valid(self):
        """IFLD-02 guard: a clean ISO date still converts."""
        value, warnings = self.converter._str_to_date(
            self.env["res.partner"],
            self.flds["date"],
            "2012-12-31",
            None,
        )
        self.assertFalse(warnings)
        self.assertEqual(value, "2012-12-31")

    def test_str_to_boolean_unknown_returns_none(self):
        """IFLD-03: an unknown boolean yields ``None`` (not ``True``) + a warning."""
        value, warnings = self.converter._str_to_boolean(
            self.env["res.partner"],
            self.flds["bool"],
            "maybe",
            None,
        )
        self.assertIsNone(value)
        self.assertTrue(warnings)

    def test_str_to_boolean_known_values(self):
        """IFLD-03 guard: recognized true/false values still resolve."""
        true_val, _w = self.converter._str_to_boolean(
            self.env["res.partner"], self.flds["bool"], "1", None
        )
        false_val, _w = self.converter._str_to_boolean(
            self.env["res.partner"], self.flds["bool"], "0", None
        )
        self.assertIs(true_val, True)
        self.assertIs(false_val, False)


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
