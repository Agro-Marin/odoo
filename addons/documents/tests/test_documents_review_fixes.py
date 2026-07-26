from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from .test_documents_common import GIF, TEXT, TransactionCaseDocuments
from odoo.addons.documents.controllers.documents import _is_safe_redirect_url
from odoo.addons.documents.tools import is_mimetype_textual


@tagged("post_install", "-at_install")
class TestDocumentsReviewHelpers(TransactionCase):
    """Pure-helper regression tests (no fixtures needed)."""

    def test_is_mimetype_textual_handles_bad_input(self):
        self.assertTrue(is_mimetype_textual("text/plain"))
        self.assertTrue(is_mimetype_textual("application/json"))
        self.assertFalse(is_mimetype_textual("image/png"))
        # Falsy / malformed input must not raise (would be a 500 in the route).
        self.assertFalse(is_mimetype_textual(False))
        self.assertFalse(is_mimetype_textual(""))
        self.assertFalse(is_mimetype_textual("notamimetype"))
        # A bare "text" has maintype "text": textual, and importantly no crash.
        self.assertTrue(is_mimetype_textual("text"))

    def test_is_safe_redirect_url(self):
        self.assertTrue(_is_safe_redirect_url("https://example.com"))
        self.assertTrue(_is_safe_redirect_url("http://example.com/x"))
        self.assertTrue(_is_safe_redirect_url("mailto:a@b.c"))
        # Schemeless / protocol-relative are resolved against the origin: fine.
        self.assertTrue(_is_safe_redirect_url("example.com/path"))
        self.assertTrue(_is_safe_redirect_url("//host/path"))
        # Dangerous schemes are rejected.
        self.assertFalse(_is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(_is_safe_redirect_url("data:text/html,<script>"))
        self.assertFalse(_is_safe_redirect_url("vbscript:msgbox"))
        self.assertFalse(_is_safe_redirect_url(""))


@tagged("post_install", "-at_install")
class TestDocumentsReviewFixes(TransactionCaseDocuments):
    """Regression tests for the correctness/security review fixes."""

    def test_lock_enforced_server_side(self):
        """A locked document's content/archive is protected from other users."""
        other = self.env["res.users"].create(
            {
                "login": "doc_user_2",
                "name": "Doc User 2",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        doc = self.document_gif
        doc.action_update_access_rights(
            partners={other.partner_id.id: ("edit", False)}
        )
        # The owner locks the document.
        doc.with_user(self.doc_user).toggle_lock()
        self.assertEqual(doc.lock_uid, self.doc_user)

        # Another editor may not replace the content nor trash it.
        with self.assertRaises(UserError):
            doc.with_user(other).write({"datas": TEXT})
        with self.assertRaises(UserError):
            doc.with_user(other).action_archive()

        # The lock owner and a manager may.
        doc.with_user(self.doc_user).write({"datas": TEXT})
        doc.with_user(self.document_manager).write({"datas": GIF})

    def test_is_folder_containing_document(self):
        """The folder-delete warning helper reports real containment."""
        # folder_b holds the gif and txt documents.
        self.assertTrue(self.folder_b.is_folder_containing_document())
        empty = self.env["documents.document"].create(
            {"type": "folder", "name": "empty", "owner_id": self.doc_user.id}
        )
        self.assertFalse(empty.is_folder_containing_document())
        # A folder holding only sub-folders (no files) is still "empty".
        self.env["documents.document"].create(
            {"type": "folder", "name": "child", "folder_id": empty.id}
        )
        self.assertFalse(empty.is_folder_containing_document())

    def test_check_automation_available_returns_bool(self):
        """The ACL-safe helper answers without an ir.module.module AccessError."""
        result = (
            self.env["documents.document"]
            .with_user(self.doc_user)
            .check_automation_available()
        )
        self.assertIsInstance(result, bool)

    def test_action_move_folder_stale_before_folder(self):
        """A concurrently-deleted before_folder must not crash the move."""
        doc_env = self.env["documents.document"].with_user(self.doc_user)
        sub1, sub2 = doc_env.create(
            [
                {
                    "type": "folder",
                    "name": name,
                    "folder_id": self.folder_a.id,
                    "owner_id": self.doc_user.id,
                }
                for name in ("sub1", "sub2")
            ]
        )
        ghost_id = sub2.id
        sub2.unlink()
        # before_folder_id references the deleted sibling: falls back gracefully.
        sub1.action_move_folder(str(self.folder_a.id), before_folder_id=ghost_id)
        self.assertEqual(sub1.folder_id, self.folder_a)

    def test_gc_clear_bin_respects_deletion_delay(self):
        """Trashed documents are purged only after the deletion delay."""
        Doc = self.env["documents.document"]
        self.env["ir.config_parameter"].sudo().set_param(
            "documents.deletion_delay", "30"
        )
        doc = Doc.create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "trash.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        doc.action_archive()
        self.assertFalse(doc.active)

        # Freshly trashed: within the delay, it survives the GC.
        Doc._gc_clear_bin()
        self.assertTrue(doc.exists())

        # Back-date past the delay: it is collected.
        self.env.cr.execute(
            "UPDATE documents_document SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - relativedelta(days=31), doc.id),
        )
        doc.invalidate_recordset(["write_date"])
        Doc._gc_clear_bin()
        self.assertFalse(doc.exists())

    def test_empty_access_ids_opts_out_of_inheritance(self):
        """Explicitly empty access_ids skips folder-member inheritance."""
        self.folder_a.action_update_access_rights(
            partners={self.portal_user.partner_id.id: ("view", False)}
        )
        # Passing an access_ids command list that clears members opts out.
        opted_out = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "no-inherit",
                "folder_id": self.folder_a.id,
                "access_ids": [Command.set([])],
            }
        )
        self._assert_no_members(opted_out)
        self.assertFalse(opted_out.access_ids)

        # Not providing access_ids still inherits (default behaviour).
        inherited = self.env["documents.document"].create(
            {"type": "folder", "name": "inherit", "folder_id": self.folder_a.id}
        )
        self.assertIn(self.portal_user.partner_id, inherited.access_ids.partner_id)

    def test_write_new_attachment_and_datas_versions_once(self):
        """Writing a new attachment together with datas archives only one version."""
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
        # Only the original attachment is archived as a previous version, not an
        # extra copy from a double-versioning path.
        self.assertEqual(doc.previous_attachment_ids, first_attachment)

    def test_request_wizard_requires_target_write_access(self):
        """The request wizard enforces write access on the linked record."""
        wizard_model = self.env["documents.request_wizard"]
        # An unknown model is rejected outright.
        bad_model = wizard_model.with_user(self.doc_user).create(
            {
                "name": "req",
                "folder_id": self.folder_a.id,
                "requestee_id": self.doc_user.partner_id.id,
                "res_model": "no.such.model",
                "res_id": 1,
            }
        )
        with self.assertRaises(UserError):
            bad_model.request_document()

        # A record the documents user cannot write to is refused.
        param = self.env["ir.config_parameter"].sudo().create(
            {"key": "documents.review_fixes_probe", "value": "x"}
        )
        restricted = wizard_model.with_user(self.doc_user).create(
            {
                "name": "req",
                "folder_id": self.folder_a.id,
                "requestee_id": self.doc_user.partner_id.id,
                "res_model": "ir.config_parameter",
                "res_id": param.id,
            }
        )
        with self.assertRaises(AccessError):
            restricted.request_document()
