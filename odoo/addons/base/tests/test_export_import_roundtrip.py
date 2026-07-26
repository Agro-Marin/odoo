"""``export_data()`` and ``load()`` are two halves of one contract.

A file produced by the export menu must be re-importable by the import menu.
Neither half had a test asserting that, and both were broken:

* ``<m2m>/id`` exported DISPLAY NAMES into an external-id column, so the file
  could not be re-imported ("No matching record found for external id 'Tag A'").
  ``<m2m>/.id`` likewise emitted names instead of database ids. Cause: a
  list-vs-tuple mismatch -- ``export_data`` normalizes paths to tuples via
  ``fix_import_export_id_paths``, while the m2m branch looked the requested
  sub-field up with ``fields2.index([name])``, which never matched, and the
  ``ValueError`` was suppressed into the display-name fallback.
* ``load()`` raised ``AttributeError``/``TypeError`` on a cell that was not a
  ``str`` (a native ``bool`` -- exactly what ``export_data`` emits for a Boolean
  column -- or an ``int``, or a ``list``). ``load()`` is RPC-exposed and
  contracts to REPORT per-field problems in ``messages``; raising turns a bad
  cell into a 500 for the whole import.
"""

from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestExportImportRoundtrip(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.tag_a = cls.env["res.partner.category"].create({"name": "rt tag A"})
        cls.tag_b = cls.env["res.partner.category"].create({"name": "rt tag B"})
        cls.country = cls.env.ref("base.be")
        cls.record = cls.Partner.create(
            {
                "name": "roundtrip probe",
                "country_id": cls.country.id,
                "category_id": [Command.set([cls.tag_a.id, cls.tag_b.id])],
            }
        )
        cls.env.flush_all()

    def _export(self, columns):
        return self.record.export_data(columns)["datas"][0]

    def test_m2m_external_id_column_exports_external_ids(self):
        """``<m2m>/id`` must emit external ids, and create the missing ones."""
        __, cell = self._export(["name", "category_id/id"])
        exported = cell.split(",")
        self.assertEqual(len(exported), 2, cell)
        resolved = [self.env.ref(xid) for xid in exported]
        self.assertEqual(
            (self.tag_a + self.tag_b),
            resolved[0] | resolved[1],
            "the /id column did not carry resolvable external ids",
        )
        for name in (self.tag_a.display_name, self.tag_b.display_name):
            self.assertNotIn(name, exported)

    def test_m2m_database_id_column_exports_database_ids(self):
        """``<m2m>/.id`` must emit database ids, not names."""
        __, cell = self._export(["name", "category_id/.id"])
        self.assertEqual(
            sorted(int(v) for v in cell.split(",")),
            sorted((self.tag_a + self.tag_b).ids),
        )

    def test_m2m_bare_column_still_exports_display_names(self):
        """No regression: a bare m2m column stays human-readable."""
        __, cell = self._export(["name", "category_id"])
        self.assertEqual(
            sorted(cell.split(",")),
            sorted([self.tag_a.display_name, self.tag_b.display_name]),
        )

    def test_m2o_columns_unchanged(self):
        """The many2one selectors already worked; pin them against the m2m fix."""
        self.assertEqual(self._export(["name", "country_id/id"])[1], "base.be")
        self.assertEqual(
            self._export(["name", "country_id/.id"])[1], str(self.country.id)
        )
        self.assertEqual(
            self._export(["name", "country_id"])[1], self.country.display_name
        )

    def test_export_then_load_roundtrips(self):
        """A file exported with /id columns must re-import to the same values."""
        columns = ["name", "country_id/id", "category_id/id", "employee", "color"]
        self.record.employee = True
        self.record.color = 3
        self.env.flush_all()

        rows = self.record.export_data(columns)["datas"]
        result = self.Partner.load(columns, rows)
        errors = [m for m in result["messages"] if m.get("type") != "warning"]
        self.assertFalse(errors, f"re-importing an export reported {errors}")
        self.assertEqual(len(result["ids"]), 1)

        imported = self.Partner.browse(result["ids"])
        self.assertEqual(imported.name, self.record.name)
        self.assertEqual(imported.country_id, self.record.country_id)
        self.assertEqual(imported.category_id, self.record.category_id)
        self.assertEqual(imported.employee, self.record.employee)
        self.assertEqual(imported.color, self.record.color)

    def test_load_accepts_native_boolean_cells(self):
        """A native bool/int in a Boolean column imports, it does not raise.

        This is what ``export_data`` emits, and what a JSON-RPC client sends for
        ``true``. ``_str_to_boolean`` used to call ``value.lower()`` directly.
        """
        for value, expected in ((True, True), (False, False), (1, True), (0, False)):
            with self.subTest(value=value):
                result = self.Partner.load(
                    ["name", "employee"], [[f"native {value!r}", value]]
                )
                errors = [m for m in result["messages"] if m.get("type") != "warning"]
                self.assertFalse(errors, f"{value!r} reported {errors}")
                self.assertEqual(len(result["ids"]), 1)
                self.assertEqual(self.Partner.browse(result["ids"]).employee, expected)

    def test_load_reports_unconvertible_cell_type_instead_of_raising(self):
        """A cell whose SHAPE no converter accepts must be reported, not raised.

        A list in a many2many column reached ``.split(',')`` on an int and blew
        up out of ``load()``, taking the whole import with it.
        """
        result = self.Partner.load(
            ["name", "category_id"], [["bad shape", [self.tag_a.id]]]
        )
        messages = result["messages"]
        self.assertTrue(messages, "an unconvertible cell was silently accepted")
        self.assertTrue(
            any(
                "cannot import a value of type" in m.get("message", "")
                for m in messages
            ),
            messages,
        )
        self.assertFalse(result["ids"])
