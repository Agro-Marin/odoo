import importlib.util
import pathlib

from odoo.tests.common import TransactionCase

_MIGRATION = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "1.8"
    / "pre-migrate_manufacturer_backfill.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("manufacturer_backfill", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestManufacturerBackfill(TransactionCase):
    """The backfill pushes template manufacturer info down to a lone variant
    that holds none, so `_compute_manufacturer_info` cannot read the archived
    variant as empty and clear the template."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.migration = _load_migration()
        cls.manufacturer = cls.env["res.partner"].create(
            {"name": "Migration Manufacturer", "is_manufacturer": True}
        )

    def _template(self, name, **vals):
        return self.env["product.template"].create({"name": name, **vals})

    def _blank_the_variants(self, template):
        self.env.flush_all()
        self.env.cr.execute(
            """
            UPDATE product_product
               SET manufacturer_id = NULL,
                   manufacturer_pname = NULL,
                   manufacturer_pref = NULL,
                   manufacturer_purl = NULL
             WHERE product_tmpl_id = %s
            """,
            (template.id,),
        )

    def _migrate(self):
        self.env.flush_all()
        self.migration.migrate(self.env.cr, "1.7")
        rowcount = self.env.cr.rowcount
        self.env.invalidate_all()
        return rowcount

    def test_a_lone_empty_variant_is_backfilled(self):
        template = self._template(
            "Migration A",
            manufacturer_id=self.manufacturer.id,
            manufacturer_pname="Name A",
            manufacturer_pref="REF-A",
            manufacturer_purl="https://example.test/a",
        )
        variant = template.product_variant_ids
        self.assertEqual(len(variant), 1)
        self._blank_the_variants(template)

        self.assertEqual(self._migrate(), 1)

        self.assertEqual(variant.manufacturer_id, self.manufacturer)
        self.assertEqual(variant.manufacturer_pname, "Name A")
        self.assertEqual(variant.manufacturer_pref, "REF-A")
        self.assertEqual(variant.manufacturer_purl, "https://example.test/a")

    def test_b_a_variant_holding_partial_data_is_left_alone(self):
        template = self._template(
            "Migration B",
            manufacturer_id=self.manufacturer.id,
            manufacturer_pref="REF-B",
        )
        variant = template.product_variant_ids
        self._blank_the_variants(template)
        variant.manufacturer_pname = "Kept"

        self.assertEqual(self._migrate(), 0)

        self.assertEqual(variant.manufacturer_pname, "Kept")
        self.assertFalse(variant.manufacturer_id)

    def test_c_a_template_with_two_variants_is_skipped(self):
        attribute = self.env["product.attribute"].create({"name": "Migration size"})
        values = self.env["product.attribute.value"].create(
            [
                {"name": "small", "attribute_id": attribute.id},
                {"name": "large", "attribute_id": attribute.id},
            ]
        )
        template = self._template(
            "Migration C",
            manufacturer_id=self.manufacturer.id,
            attribute_line_ids=[
                (
                    0,
                    0,
                    {"attribute_id": attribute.id, "value_ids": [(6, 0, values.ids)]},
                )
            ],
        )
        self.assertEqual(len(template.product_variant_ids), 2)
        self._blank_the_variants(template)

        self.assertEqual(self._migrate(), 0)

        self.assertFalse(any(template.product_variant_ids.mapped("manufacturer_id")))

    def test_d_a_template_holding_nothing_pushes_nothing(self):
        template = self._template("Migration D")
        self._blank_the_variants(template)

        self.assertEqual(self._migrate(), 0)

        self.assertFalse(template.product_variant_ids.manufacturer_id)
