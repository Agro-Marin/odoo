import psycopg

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestCatalogMixin(TransactionCase):
    """The mixin's contract, exercised through ``tag.tag``.

    ``tag.tag`` is the concrete inheritor that ships with ``base``. It
    re-scopes the uniqueness rule to ``parent_id``, which is what makes it
    useful here: both halves of the contract -- the fields, and the fact that
    an inheritor may re-scope but not drop the rule -- are visible on it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tag = cls.env["tag.tag"]
        cls.root = cls.Tag.create({"name": "Rootcat"})

    def test_name_keeps_mixin_attributes_through_partial_override(self):
        """tag.mixin restates ``name`` for its label only."""
        field = self.Tag._fields["name"]
        self.assertTrue(field.required)
        self.assertTrue(field.translate)
        self.assertEqual(field.string, "Tag Name")

    def test_active_keeps_mixin_default_through_partial_override(self):
        field = self.Tag._fields["active"]
        self.assertTrue(self.Tag.default_get(["active"])["active"])
        self.assertEqual(field.help, "Archive a tag to hide it without deleting it.")

    def test_uniqueness_rule_is_inherited_and_rescoped(self):
        """The inheritor's scope wins, and there is exactly one rule."""
        rules = [
            obj
            for name, obj in self.Tag._table_objects.items()
            if name.endswith("name_src_uniq")
        ]
        self.assertEqual(len(rules), 1)
        self.assertIn("parent_id", rules[0].get_definition(self.env.registry))

    @mute_logger("odoo.sql_db")
    def test_duplicate_name_under_same_parent_is_refused(self):
        self.Tag.create({"name": "Twin", "parent_id": self.root.id})
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.cr.savepoint():
                self.Tag.create({"name": "Twin", "parent_id": self.root.id})

    def test_same_name_under_different_parents_is_allowed(self):
        other_root = self.Tag.create({"name": "Othercat"})
        self.Tag.create({"name": "Shared", "parent_id": self.root.id})
        self.Tag.create({"name": "Shared", "parent_id": other_root.id})
        self.env.flush_all()

    @mute_logger("odoo.sql_db")
    def test_null_scope_still_collides(self):
        """NULLS NOT DISTINCT: two parentless records are compared, not skipped."""
        self.Tag.create({"name": "Loner"})
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.cr.savepoint():
                self.Tag.create({"name": "Loner"})

    @mute_logger("odoo.sql_db")
    def test_archived_record_keeps_its_name_reserved(self):
        tag = self.Tag.create({"name": "Retired"})
        tag.active = False
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.cr.savepoint():
                self.Tag.create({"name": "Retired"})

    @mute_logger("odoo.sql_db")
    def test_translation_document_does_not_defeat_the_rule(self):
        """The regression a plain ``UNIQUE(name)`` would let through.

        The second record is created in another language, so Odoo writes both
        the source term and that language into the jsonb column. Its whole
        document therefore differs from the first record's, and a constraint
        comparing documents would see no duplicate; the index compares the
        source term and does.
        """
        self.env["res.lang"]._activate_lang("es_MX")
        self.Tag.create({"name": "Whitefly"})
        self.env.flush_all()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.cr.savepoint():
                self.Tag.with_context(lang="es_MX").create({"name": "Whitefly"})
