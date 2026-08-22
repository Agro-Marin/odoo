from psycopg.errors import IntegrityError

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from .test_documents_common import TransactionCaseDocuments


class TestTags(TransactionCase):
    def test_create_tag(self):
        tag = self.env["documents.tag"].create({"name": "Foo"})
        self.assertTrue(tag.sequence > 0, "should have a non-zero sequence")

    def test_remove_tag(self):
        tag, used_tag = self.env["documents.tag"].create(
            [{"name": "Foo"}, {"name": "Used Tag"}]
        )

        self.env["ir.model.data"].create(
            {
                "name": "used_tag",
                "module": "documents",
                "model": "documents.tag",
                "res_id": used_tag.id,
            }
        )
        action_server = self.env["ir.actions.server"].create(
            {
                "name": "Test Action",
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "update_path": "tag_ids",
                "usage": "ir_actions_server",
                "state": "object_write",
                "update_m2m_operation": "add",
                "resource_ref": "documents.tag,%s" % used_tag.id,
            }
        )

        tag.unlink()
        self.assertFalse(tag.exists(), "Tag 'Foo' should be deleted.")
        with self.assertRaises(
            UserError,
            msg="Used Tag should not be deletable as it's used in a server action.",
        ):
            used_tag.unlink()

        action_server.unlink()
        used_tag.unlink()
        self.assertFalse(
            used_tag.exists(),
            "Formerly used tag should be deleted if server action has been deleted.",
        )


@tagged("post_install", "-at_install")
class TestDocumentsTagUniqueness(TransactionCaseDocuments):

    def test_f6_tag_name_unique_same_language(self):
        Tag = self.env["documents.tag"]
        Tag.create({"name": "Audit3DupTag"})
        with (
            self.assertRaises(IntegrityError),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            Tag.create({"name": "Audit3DupTag"})
        with (
            self.assertRaises(IntegrityError),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            Tag.create([{"name": "Audit3Batch"}, {"name": "Audit3Batch"}])

    def test_f6_tag_name_unique_across_translations(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        Tag = self.env["documents.tag"]
        tag = Tag.create({"name": "Audit3TransTag"})
        tag.with_context(lang="fr_FR").name = "Audit3TransTagFR"
        with (
            self.assertRaises(IntegrityError),
            mute_logger("odoo.db.cursor"),
            self.cr.savepoint(),
        ):
            Tag.create({"name": "Audit3TransTag"})
        self.assertEqual(
            Tag.search([("name", "=", "Audit3TransTag")]),
            tag,
        )
