import psycopg

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "partner_scoring")
class TestResPartnerAttribute(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attribute = cls.env["res.partner.attribute"]
        cls.Value = cls.env["res.partner.attribute.value"]
        cls.attribute = cls.Attribute.create(
            {"name": "Test Partner Attribute", "value_type": "single"}
        )
        cls.value = cls.Value.create(
            {"name": "Test Value", "attribute_id": cls.attribute.id}
        )

    def test_inherits_mixin(self):
        registry = self.env.registry
        self.assertTrue(
            issubclass(registry["res.partner.attribute"], registry["mixin.attribute"])
        )
        self.assertTrue(
            issubclass(
                registry["res.partner.attribute.value"],
                registry["mixin.attribute.value"],
            )
        )
        self.assertIn("value_type", self.Attribute._fields)

    def test_value_types(self):
        types = dict(self.Attribute._fields["value_type"].selection)
        self.assertEqual(set(types), {"single", "multi"})

    def test_attribute_name_unique(self):
        with (
            self.assertRaises(psycopg.IntegrityError),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            self.Attribute.create({"name": "Test Partner Attribute"})
            self.env.flush_all()

    def test_value_name_unique_within_attribute(self):
        with (
            self.assertRaises(psycopg.IntegrityError),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            self.Value.create({"name": "Test Value", "attribute_id": self.attribute.id})
            self.env.flush_all()

    def test_value_name_reusable_across_attributes(self):
        other = self.Attribute.create({"name": "Other Attribute"})
        twin = self.Value.create({"name": "Test Value", "attribute_id": other.id})
        self.assertTrue(twin)

    def test_ondelete_cascade_from_attribute(self):
        attr = self.Attribute.create({"name": "Temp Attribute"})
        val = self.Value.create({"name": "Temp Value", "attribute_id": attr.id})
        attr.unlink()
        self.assertFalse(val.exists())
