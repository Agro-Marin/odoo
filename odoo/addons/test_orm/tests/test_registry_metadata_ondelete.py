"""``ondelete="restrict"`` is refused when the comodel describes the registry.

The rule: the ``ir.model*`` reflection models and ``ir.module.module`` have
their rows deleted and rewritten on every install, upgrade and uninstall, so a
restricting foreign key into one blocks the operation that maintains it.

It was enforced against ``IR_MODELS``, a tuple of seven model names hardcoded
in ``orm/fields/base.py`` -- Layer 1 of the ORM naming addon-owned models, and
covered by no test at all. It is now ``BaseModel._is_registry_metadata``,
declared by the models it describes. Both halves are asserted here: that the
flag is where it should be, and that the check still fires.
"""

from odoo import fields
from odoo.tests.common import TransactionCase

#: The models whose rows the module system owns. Spelled out rather than
#: derived, so that dropping a declaration fails instead of shrinking the
#: expectation with it.
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
        """A default on the metadata mixin, not an attribute only some carry --
        ``Many2one.setup_nonrelated`` reads it on an arbitrary comodel."""
        for model_cls in self.env.registry.values():
            self.assertIn(model_cls._is_registry_metadata, (True, False))


class TestRestrictOntoRegistryMetadataIsRefused(TransactionCase):
    def _setup_m2o(self, comodel_name, ondelete):
        """A Many2one far enough along to run ``setup_nonrelated``.

        ``Many2one(...)`` only stashes its kwargs in ``_args__``; the named
        attributes appear when ``__set_name__``/``_setup_attrs__`` run against
        an owning model class. This test has no such class, so the three
        attributes the method reads are assigned directly. Setting them through
        the constructor instead leaves ``self.ondelete`` as ``None``, the
        method fills in a default, and the assertion silently tests nothing --
        which is what the first version of this file did.
        """
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
        """Only ``restrict`` is refused -- cascade follows the deletion."""
        field = self._setup_m2o("ir.model", ondelete="cascade")
        field.setup_nonrelated(self.env["res.partner"])
        self.assertEqual(field.ondelete, "cascade")
