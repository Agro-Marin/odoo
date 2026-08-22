import base64
import io

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged, users

from .test_documents_common import GIF, TEXT, TransactionCaseDocuments


def _png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


class TestDocumentsVersioning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Version User",
                "login": "round4_versions",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )

    def _document_with_versions(self, contents):
        document = (
            self.env["documents.document"]
            .with_user(self.user)
            .create({"name": "versioned.txt", "type": "binary", "raw": contents[0]})
        )
        for content in contents[1:]:
            document.write({"raw": content})
        document.invalidate_recordset()
        return document

    def test_restore_brings_back_a_chosen_version_without_deleting_any(self):
        document = self._document_with_versions([b"v1", b"v2", b"v3"])
        self.assertEqual(bytes(document.attachment_id.raw), b"v3")
        self.assertEqual(len(document.previous_attachment_ids), 2)
        oldest = min(document.previous_attachment_ids, key=lambda a: a.id)
        self.assertEqual(bytes(oldest.raw), b"v1")

        document.with_user(self.user).action_restore_version(oldest.id)
        document.invalidate_recordset()

        self.assertEqual(bytes(document.attachment_id.raw), b"v1")
        self.assertEqual(
            {bytes(a.raw) for a in document.previous_attachment_ids},
            {b"v2", b"v3"},
            "the version it replaced joins the history; nothing is destroyed",
        )

    def test_restore_is_recorded_on_the_document(self):
        document = self._document_with_versions([b"v1", b"v2"])
        previous = document.previous_attachment_ids
        before = len(document.message_ids)

        document.with_user(self.user).action_restore_version(previous.id)
        document.invalidate_recordset()

        self.assertGreater(len(document.message_ids), before)
        self.assertTrue(
            any(
                "Version restored" in (body or "")
                for body in document.message_ids.mapped("body")
            ),
            "a content revert must leave a trace",
        )

    def test_restore_refuses_a_foreign_attachment(self):
        document = self._document_with_versions([b"v1", b"v2"])
        stranger = self.env["ir.attachment"].create(
            {"name": "elsewhere.txt", "raw": b"nope"}
        )
        with self.assertRaises(UserError):
            document.with_user(self.user).action_restore_version(stranger.id)

    def test_restore_requires_edit(self):
        document = self._document_with_versions([b"v1", b"v2"])
        previous = document.previous_attachment_ids
        viewer = self.env["res.users"].create(
            {
                "name": "Version Viewer",
                "login": "round4_version_viewer",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        document.action_update_access_rights(
            partners={viewer.partner_id: ("view", False)}
        )
        self.assertEqual(document.with_user(viewer).user_permission, "view")

        with self.assertRaises(AccessError):
            document.with_user(viewer).action_restore_version(previous.id)

    def test_history_is_unbounded_by_default(self):
        document = self._document_with_versions([b"v1", b"v2", b"v3", b"v4"])
        self.assertEqual(len(document.previous_attachment_ids), 3)

    def test_history_is_pruned_to_the_configured_maximum(self):
        self.env["ir.config_parameter"].sudo().set_param("documents.max_versions", "2")
        document = self._document_with_versions([b"v1", b"v2", b"v3", b"v4"])

        self.assertEqual(len(document.previous_attachment_ids), 2)
        self.assertEqual(
            {bytes(a.raw) for a in document.previous_attachment_ids},
            {b"v2", b"v3"},
            "the oldest versions are the ones dropped",
        )
        self.assertEqual(bytes(document.attachment_id.raw), b"v4")


@tagged("post_install", "-at_install")
class TestDocumentsVersionDeletion(TransactionCaseDocuments):
    @users("documents@example.com")
    def test_delete_from_history_refused_for_a_viewer(self):
        document = (
            self.env["documents.document"]
            .sudo()
            .create(
                {
                    "name": "versioned.txt",
                    "type": "binary",
                    "owner_id": self.document_manager.id,
                    "access_internal": "view",
                    "raw": base64.b64encode(b"v1"),
                }
            )
        )
        document.write({"raw": base64.b64encode(b"v2")})
        old_version = document.previous_attachment_ids
        self.assertTrue(old_version)

        as_viewer = self.env["documents.document"].browse(document.id)
        self.assertEqual(as_viewer.user_permission, "view")
        with self.assertRaises(AccessError) as capture:
            as_viewer.action_delete_from_history(old_version.id)
        self.assertNotIn(
            old_version.name,
            str(capture.exception),
            "the refusal must not name content the user cannot see",
        )
        self.assertTrue(old_version.sudo().exists())

    def test_delete_current_version_is_logged(self):
        document = self.env["documents.document"].create(
            {
                "name": "versioned.txt",
                "type": "binary",
                "raw": base64.b64encode(b"v1"),
            }
        )
        document.write({"raw": base64.b64encode(b"v2")})
        first_version = document.previous_attachment_ids
        current = document.attachment_id
        self.assertEqual(len(first_version), 1)
        self.assertNotEqual(current, first_version)

        messages_before = len(document.message_ids)
        document.action_delete_from_history(current.id)

        self.assertEqual(document.attachment_id, first_version)
        self.assertGreater(
            len(document.message_ids),
            messages_before,
            "a content rollback must be recorded in the chatter",
        )

    def test_delete_from_history_rejects_a_foreign_attachment(self):
        document = self.env["documents.document"].create(
            {"name": "a.txt", "type": "binary", "raw": base64.b64encode(b"a")}
        )
        other = self.env["documents.document"].create(
            {"name": "b.txt", "type": "binary", "raw": base64.b64encode(b"b")}
        )
        with self.assertRaises(UserError):
            document.action_delete_from_history(other.attachment_id.id)


@tagged("post_install", "-at_install")
class TestDocumentsVersionCreation(TransactionCaseDocuments):
    def test_write_new_attachment_and_datas_versions_once(self):
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "versioned.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        first_attachment = doc.attachment_id
        new_attachment = self.env["ir.attachment"].create(
            {"name": "replacement", "datas": GIF}
        )
        doc.write({"attachment_id": new_attachment.id, "datas": GIF})
        self.assertEqual(doc.previous_attachment_ids, first_attachment)
