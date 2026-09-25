from datetime import timedelta

from odoo import fields
from odoo.modules.module import get_module_path, load_script
from odoo.tests import tagged

from .test_document_common import TransactionCaseDocuments
from odoo.addons.base.models.access_link import LinkRefused


@tagged("post_install", "-at_install")
class TestFileExtensionMigration(TransactionCaseDocuments):
    def _migrate(self):
        script = load_script(
            f"{get_module_path('document')}/migrations/1.20/post-migrate.py",
            "document_1_20_post_migrate",
        )
        self.env.flush_all()
        script.migrate(self.env.cr, "1.19")

    def _document(self, name, stored_extension):
        document = self.env["document.document"].create(
            {"name": name, "raw": b"x", "folder_id": self.folder_a.id}
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE document_document SET file_extension = %s WHERE id = %s",
            [stored_extension, document.id],
        )
        document.invalidate_recordset(["file_extension"])
        return document

    def test_a_derived_short_extension_becomes_the_file_s_own(self):
        markdown = self._document("notes.markdown", "md")
        archive = self._document("page.mhtml", "eml")
        self._migrate()
        self.assertEqual(markdown.file_extension, "markdown")
        self.assertEqual(archive.file_extension, "mhtml")

    def test_a_real_short_extension_and_an_operator_s_choice_are_kept(self):
        plain = self._document("README.md", "md")
        chosen = self._document("manual.markdown", "txt")
        self._migrate()
        self.assertEqual(plain.file_extension, "md")
        self.assertEqual(chosen.file_extension, "txt")

    def test_a_fresh_install_does_nothing(self):
        markdown = self._document("notes.markdown", "md")
        script = load_script(
            f"{get_module_path('document')}/migrations/1.20/post-migrate.py",
            "document_1_20_post_migrate_fresh",
        )
        script.migrate(self.env.cr, None)
        markdown.invalidate_recordset(["file_extension"])
        self.assertEqual(markdown.file_extension, "md")


@tagged("post_install", "-at_install")
class TestDocumentTokenMigration(TransactionCaseDocuments):
    def _script(self, kind):
        return load_script(
            f"{get_module_path('document')}/migrations/1.21/{kind}-migrate.py",
            f"document_1_21_{kind}_migrate",
        )

    def test_a_shared_document_keeps_its_old_url_and_gains_a_new_one(self):
        shared, private = self.env["document.document"].create(
            [
                {"name": "shared.txt", "raw": b"x", "folder_id": self.folder_a.id},
                {"name": "private.txt", "raw": b"y", "folder_id": self.folder_a.id},
            ]
        )
        self.env.flush_all()
        self.env.cr.execute(
            "ALTER TABLE document_document ADD COLUMN document_token varchar NOT NULL "
            "DEFAULT 'short'"
        )
        self.env.cr.execute(
            "UPDATE document_document SET document_token = %s, access_via_link = 'view' "
            "WHERE id = %s",
            ["Qx7kP2mN9vR4tY6wZ1aB3c", shared.id],
        )
        self.env.cr.execute(
            "UPDATE document_document SET document_token = %s WHERE id = %s",
            ["Zz9yX8wV7uT6sR5qP4oN3m", private.id],
        )
        self.env.invalidate_all()

        self._script("pre").migrate(self.env.cr, "1.20")
        self._script("post").migrate(self.env.cr, "1.20")

        Link = self.env["access.link"]
        old = Link._resolve(
            "Qx7kP2mN9vR4tY6wZ1aB3c", model=shared._name, res_id=shared.id
        )
        self.assertEqual(old.record, shared)
        self.assertEqual(old.link.legacy_source, "document.document.document_token")
        self.assertAlmostEqual(
            old.link.date_to,
            fields.Datetime.now() + timedelta(days=365),
            delta=timedelta(minutes=5),
        )
        new_token = shared.access_token.rpartition("o")[0]
        self.assertTrue(new_token)
        self.assertNotEqual(new_token, "Qx7kP2mN9vR4tY6wZ1aB3c")
        self.assertEqual(Link._resolve(new_token).link.date_to, old.link.date_to)
        with self.assertRaises(LinkRefused):
            Link._resolve("Zz9yX8wV7uT6sR5qP4oN3m")
        self.env.cr.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'document_document' AND column_name = 'document_token'"
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_a_database_without_the_token_column_is_left_alone(self):
        self._script("pre").migrate(self.env.cr, "1.20")
        self._script("post").migrate(self.env.cr, "1.20")
        self.assertFalse(
            self.env["access.link"].search_count([("legacy_source", "!=", False)])
        )
