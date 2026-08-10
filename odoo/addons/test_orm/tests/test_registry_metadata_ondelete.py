from odoo import fields
from odoo.tests.common import TransactionCase

REGISTRY_METADATA_MODELS = (
    "ir.model",
    "ir.model.data",
    "ir.model.fields",
    "ir.model.fields.selection",
    "ir.model.relation",
    "ir.model.constraint",
    "ir.module.module",
)


class TestRegistryMetadataFlag(TransactionCase):
    def test_the_reflection_models_declare_it(self):
        for name in REGISTRY_METADATA_MODELS:
            with self.subTest(model=name):
                self.assertTrue(self.env[name]._is_registry_metadata)

    def test_an_ordinary_model_does_not(self):
        for name in ("res.partner", "res.users", "res.company", "ir.ui.view"):
            with self.subTest(model=name):
                self.assertFalse(self.env[name]._is_registry_metadata)

    def test_it_is_readable_on_every_model(self):
        for model_cls in self.env.registry.values():
            self.assertIn(model_cls._is_registry_metadata, (True, False))


class TestRestrictOntoRegistryMetadataIsRefused(TransactionCase):
    def _setup_m2o(self, comodel_name, ondelete):
        field = fields.Many2one(comodel_name)
        field.name = "probe_field"
        field.model_name = "res.partner"
        field.comodel_name = comodel_name
        field.ondelete = ondelete
        return field

    def test_restrict_onto_a_reflection_model_raises(self):
        for name in REGISTRY_METADATA_MODELS:
            with self.subTest(model=name):
                field = self._setup_m2o(name, ondelete="restrict")
                with self.assertRaises(ValueError) as caught:
                    field.setup_nonrelated(self.env["res.partner"])
                self.assertIn("restrict", str(caught.exception))

    def test_restrict_onto_an_ordinary_model_is_allowed(self):
        field = self._setup_m2o("res.company", ondelete="restrict")
        field.setup_nonrelated(self.env["res.partner"])
        self.assertEqual(field.ondelete, "restrict")

    def test_cascade_onto_a_reflection_model_is_allowed(self):
        field = self._setup_m2o("ir.model", ondelete="cascade")
        field.setup_nonrelated(self.env["res.partner"])
        self.assertEqual(field.ondelete, "cascade")
