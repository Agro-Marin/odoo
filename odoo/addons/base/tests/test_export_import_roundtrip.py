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
        __, cell = self._export(["name", "category_id/.id"])
        self.assertEqual(
            sorted(int(v) for v in cell.split(",")),
            sorted((self.tag_a + self.tag_b).ids),
        )

    def test_m2m_bare_column_still_exports_display_names(self):
        __, cell = self._export(["name", "category_id"])
        self.assertEqual(
            sorted(cell.split(",")),
            sorted([self.tag_a.display_name, self.tag_b.display_name]),
        )

    def test_m2o_columns_unchanged(self):
        self.assertEqual(self._export(["name", "country_id/id"])[1], "base.be")
        self.assertEqual(
            self._export(["name", "country_id/.id"])[1], str(self.country.id)
        )
        self.assertEqual(
            self._export(["name", "country_id"])[1], self.country.display_name
        )

    def test_export_then_load_roundtrips(self):
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
        result = self.Partner.load(
            ["name", "category_id"], [["bad shape", [self.tag_a.id]]]
        )
        messages = result["messages"]
        self.assertTrue(messages, "an unconvertible cell was silently accepted")
        self.assertTrue(
            any("of type 'list'" in m.get("message", "") for m in messages),
            messages,
        )
        self.assertFalse(result["ids"])
