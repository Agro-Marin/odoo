from psycopg.types.json import Json

from odoo.tests import TransactionCase, tagged
from odoo.tools import SQL

LANG = "fr_FR"
MODULE = "test_inherited_label"


@tagged("post_install", "-at_install")
class TestInheritedFieldTranslation(TransactionCase):
    """A field a mixin gives every model that inherits it has one label, and a
    module's catalogue can only name the models of its own dependency closure:
    calendar cannot list account.move, whose activity_calendar_event_id it
    injects. The label read untranslated on every model the template could not
    name."""

    def _field(self, model, name):
        return self.env["ir.model.fields"]._get(model, name)

    def _set(self, field, column, value):
        self.env.cr.execute(
            SQL(
                "UPDATE ir_model_fields SET %s = %s WHERE id = %s",
                SQL.identifier(column),
                Json(value),
                field.id,
            )
        )
        field.invalidate_recordset([column])

    def _get(self, field, column):
        self.env.cr.execute(
            SQL(
                "SELECT %s FROM ir_model_fields WHERE id = %s",
                SQL.identifier(column),
                field.id,
            )
        )
        return self.env.cr.fetchone()[0] or {}

    def _load(self):
        self.env["ir.module.module"]._load_module_terms([MODULE], [LANG])

    def setUp(self):
        super().setUp()
        self.mixin = self._field("mixin.tag", "code")
        self.nested = self._field("mixin.tag.nested", "code")
        self.model = self._field("res.partner.tag", "code")
        label = self._get(self.mixin, "field_description")["en_US"]
        for field in (self.mixin, self.nested, self.model):
            self.assertEqual(
                self._get(field, "field_description"),
                {"en_US": label},
                "fixture: one label, and no translation yet",
            )
        self.label = label
        self.env["ir.model.data"].create(
            [
                {
                    "module": MODULE,
                    "name": f"field_{field.model.replace('.', '_')}__code",
                    "model": "ir.model.fields",
                    "res_id": field.id,
                }
                for field in (self.nested, self.model)
            ]
        )

    def test_a_model_takes_the_translation_of_the_label_its_mixin_gave_it(self):
        self._set(self.mixin, "field_description", {"en_US": self.label, LANG: "M"})
        self._load()
        self.assertEqual(self._get(self.model, "field_description").get(LANG), "M")
        self.assertEqual(self._get(self.nested, "field_description").get(LANG), "M")

    def test_the_help_travels_the_same_way(self):
        help_en = self._get(self.mixin, "help")["en_US"]
        self.assertEqual(self._get(self.model, "help"), {"en_US": help_en})
        self._set(self.mixin, "help", {"en_US": help_en, LANG: "aide"})
        self._load()
        self.assertEqual(self._get(self.model, "help").get(LANG), "aide")

    def test_the_nearest_ancestor_that_has_one_wins(self):
        self._set(self.mixin, "field_description", {"en_US": self.label, LANG: "M"})
        self._set(self.nested, "field_description", {"en_US": self.label, LANG: "N"})
        self._load()
        self.assertEqual(self._get(self.model, "field_description").get(LANG), "N")

    def test_a_translation_of_its_own_is_kept(self):
        self._set(self.mixin, "field_description", {"en_US": self.label, LANG: "M"})
        self._set(self.model, "field_description", {"en_US": self.label, LANG: "own"})
        self._load()
        self.assertEqual(self._get(self.model, "field_description").get(LANG), "own")

    def test_a_label_the_model_changed_is_not_the_mixin_label(self):
        self._set(self.mixin, "field_description", {"en_US": self.label, LANG: "M"})
        self._set(self.model, "field_description", {"en_US": "Reference"})
        self._load()
        self.assertEqual(
            self._get(self.model, "field_description"), {"en_US": "Reference"}
        )

    def test_a_model_outside_the_ancestry_lends_nothing(self):
        stranger = self.env["ir.model.fields"].search(
            [("name", "=", "code"), ("model", "=", "res.country")]
        )
        self.assertTrue(stranger, "fixture: a same-named field of an unrelated model")
        self._set(stranger, "field_description", {"en_US": self.label, LANG: "S"})
        self._load()
        self.assertNotIn(LANG, self._get(self.model, "field_description"))

    def test_a_row_the_loaded_modules_did_not_reflect_waits_for_its_own(self):
        other = self._field("tag.tag", "code")
        self.assertEqual(self._get(other, "field_description"), {"en_US": self.label})
        self._set(self.mixin, "field_description", {"en_US": self.label, LANG: "M"})
        self._load()
        self.assertNotIn(LANG, self._get(other, "field_description"))
        self.env["ir.model.fields"]._update_inherited_translations(["base"], [LANG])
        self.assertEqual(self._get(other, "field_description").get(LANG), "M")

    def test_a_delegated_field_takes_its_parents_translation(self):
        parent = self._field("res.partner", "street")
        heir = self._field("res.users", "street")
        label = self._get(parent, "field_description")["en_US"]
        self.assertEqual(self._get(heir, "field_description"), {"en_US": label})
        self.env["ir.model.data"].create(
            {
                "module": MODULE,
                "name": "field_res_users__street",
                "model": "ir.model.fields",
                "res_id": heir.id,
            }
        )
        self._set(parent, "field_description", {"en_US": label, LANG: "rue"})
        self._load()
        self.assertEqual(self._get(heir, "field_description").get(LANG), "rue")
