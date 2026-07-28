"""Regression tests for the round-5 audit findings.

Every test here fails on the code as it stood before the fix it guards.
"""

import base64
import io

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import users

from .test_documents_common import TransactionCaseDocuments


def _png(color):
    """Return a base64 PNG, i.e. content `image_process` can actually decode."""
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


class TestDocumentsAuditRound5(TransactionCaseDocuments):
    # ------------------------------------------------------------------
    # _compute_thumbnail must not observe `bin_size`
    # ------------------------------------------------------------------

    def test_thumbnail_survives_a_web_save(self):
        """Replacing content through the web client keeps the thumbnail.

        `web_save` reads back with `bin_size=True` unconditionally
        (`web_read.py`), and `_compute_thumbnail` also produces
        `thumbnail_status`, a Selection -- so `Binary.compute_value` does not
        clear the flag for it. Reading `raw` there yielded `b"129.00 bytes"`,
        `image_process` refused it, and the compute STORED
        `thumbnail_status='error'` with an empty thumbnail.
        """
        document = self.env["documents.document"].create(
            {"name": "pic.png", "type": "binary", "datas": _png((10, 200, 10))}
        )
        self.assertEqual(document.thumbnail_status, "present")
        self.assertTrue(document.thumbnail)

        result = document.web_save(
            {"datas": _png((10, 10, 200))}, {"thumbnail_status": {}}
        )

        self.assertEqual(result[0]["thumbnail_status"], "present")
        document.invalidate_recordset()
        self.assertEqual(document.thumbnail_status, "present")
        self.assertTrue(document.thumbnail)

    def test_thumbnail_recompute_under_bin_size(self):
        """The compute reads the payload even when the env carries `bin_size`."""
        document = self.env["documents.document"].create(
            {"name": "pic.png", "type": "binary", "datas": _png((200, 30, 30))}
        )
        self.env.flush_all()
        self.env.invalidate_all()
        for field_name in ("thumbnail", "thumbnail_status"):
            self.env.add_to_compute(
                self.env["documents.document"]._fields[field_name], document
            )

        self.assertEqual(
            document.with_context(bin_size=True).thumbnail_status, "present"
        )
        self.env.flush_all()
        document.invalidate_recordset()
        self.assertTrue(document.thumbnail)

    def test_thumbnail_status_error_for_undecodable_content(self):
        """A file that only claims to be an image still reports an error."""
        document = self.env["documents.document"].create(
            {
                "name": "not-an-image.png",
                "type": "binary",
                "datas": base64.b64encode(b"certainly not a png"),
            }
        )
        document.attachment_id.sudo().mimetype = "image/png"
        document.invalidate_recordset()
        self.assertEqual(document.thumbnail_status, "error")
        self.assertFalse(document.thumbnail)

    # ------------------------------------------------------------------
    # moving into a shortcut-to-folder through `user_folder_id`
    # ------------------------------------------------------------------

    @users("dtdm")
    def test_move_into_shortcut_folder_via_user_folder_id(self):
        """`user_folder_id` resolves a shortcut parent, like `folder_id` does.

        The web client sends `user_folder_id`; the re-entrant `write` used to
        carry the (already normalised) shortcut value alongside the resolved
        `folder_id`, and `_clean_vals_for_user_folder_id` then rejected its own
        output with "Conflicting values passed with user_folder_id".
        """
        Document = self.env["documents.document"]
        target = Document.create({"name": "target folder", "type": "folder"})
        shortcut = target.action_create_shortcut(location_user_folder_id="MY")

        via_user_folder = Document.create({"name": "moved by tree", "type": "binary"})
        via_user_folder.write({"user_folder_id": str(shortcut.id)})
        self.assertEqual(via_user_folder.folder_id, target)

        via_folder = Document.create({"name": "moved by field", "type": "binary"})
        via_folder.write({"folder_id": shortcut.id})
        self.assertEqual(
            via_folder.folder_id,
            target,
            "both spellings of the same move must land in the same folder",
        )

    # ------------------------------------------------------------------
    # create() must return records in the order of vals_list
    # ------------------------------------------------------------------

    def test_create_preserves_vals_list_order(self):
        """`create()` honours the `@api.model_create_multi` ordering contract.

        `_prepare_create_values` groups by `res_model` to call
        `_prepare_create_values_for_model`; `odoo.tools.groupby` gathers every
        element with the same key, so appending group by group reordered the
        list whenever two models interleave -- and the ORM returns its records
        in exactly that order.
        """
        partner = self.env["res.partner"].create({"name": "linked record"})
        attachments = (
            self.env["ir.attachment"]
            .with_context(no_document=True)
            .create(
                [
                    {"name": "a.txt", "raw": b"AAA"},
                    {
                        "name": "b.txt",
                        "raw": b"BBB",
                        "res_model": "res.partner",
                        "res_id": partner.id,
                    },
                    {"name": "c.txt", "raw": b"CCC"},
                ]
            )
        )
        vals_list = [
            {"name": name, "attachment_id": attachment.id}
            for name, attachment in zip("ABC", attachments, strict=True)
        ]

        documents = self.env["documents.document"].create(vals_list)

        self.assertEqual(documents.mapped("name"), ["A", "B", "C"])
        for document, vals in zip(documents, vals_list, strict=True):
            self.assertEqual(document.attachment_id.id, vals["attachment_id"])
        # and each self-linked attachment points back at its OWN document
        for document in documents:
            attachment = document.attachment_id
            if attachment.res_model == "documents.document":
                self.assertEqual(attachment.res_id, document.id)

    # ------------------------------------------------------------------
    # favourites are a preference, but still require read access
    # ------------------------------------------------------------------

    @users("documents@example.com")
    def test_toggle_favorited_requires_read_access(self):
        """A user with no permission cannot plant a favourite on a document."""
        hidden = (
            self.env["documents.document"]
            .sudo()
            .create(
                {
                    "name": "hidden",
                    "type": "binary",
                    "owner_id": self.document_manager.id,
                    "access_internal": "none",
                    "access_via_link": "none",
                }
            )
        )
        document = self.env["documents.document"].browse(hidden.id)
        self.assertEqual(document.user_permission, "none")

        with self.assertRaises(AccessError):
            document.toggle_favorited_multi()
        with self.assertRaises(AccessError):
            document.toggle_favorited()

        self.assertNotIn(self.env.user, hidden.favorited_ids)

    @users("documents@example.com")
    def test_toggle_favorited_still_works_for_a_viewer(self):
        """Favouriting stays available on a document one may only view."""
        shared = (
            self.env["documents.document"]
            .sudo()
            .create(
                {
                    "name": "shared",
                    "type": "binary",
                    "owner_id": self.document_manager.id,
                    "access_internal": "view",
                }
            )
        )
        document = self.env["documents.document"].browse(shared.id)
        self.assertEqual(document.user_permission, "view")

        self.assertTrue(document.toggle_favorited())
        self.assertIn(self.env.user, shared.favorited_ids)
        self.assertFalse(document.toggle_favorited())
        self.assertNotIn(self.env.user, shared.favorited_ids)

    # ------------------------------------------------------------------
    # version deletion: own wording, and a chatter trace
    # ------------------------------------------------------------------

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
        """Rolling the content back by deleting the current version leaves a trace."""
        document = self.env["documents.document"].create(
            {
                "name": "versioned.txt",
                "type": "binary",
                "raw": base64.b64encode(b"v1"),
            }
        )
        # A content write keeps the same `attachment_id` and files a *copy* of
        # the outgoing bytes in the history, so the previous version is the
        # freshly added history entry, not the original record.
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

    # ------------------------------------------------------------------
    # autovacuum re-queue contract
    # ------------------------------------------------------------------

    def test_gc_clear_bin_reports_progress(self):
        """A full batch tells the vacuum there is more to do.

        Returning ``None`` capped trash expiry at one batch per daily vacuum.
        """
        Document = self.env["documents.document"]
        self.assertEqual(Document._gc_clear_bin(), (0, False))

        documents = Document.create(
            [{"name": f"trash {i}", "type": "binary"} for i in range(3)]
        )
        documents.action_archive()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE documents_document SET write_date = write_date - interval '1 year'"
            " WHERE id = ANY(%s)",
            [documents.ids],
        )
        self.env.invalidate_all()

        done, more = Document._gc_clear_bin()
        self.assertEqual(done, 3)
        self.assertFalse(more)
        self.assertFalse(documents.exists())

    def test_gc_expired_access_reports_progress(self):
        Access = self.env["documents.access"]
        self.assertEqual(Access._gc_expired(), (0, False))

        document = self.env["documents.document"].create(
            {"name": "shared.txt", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "expiring member"})
        Access.create(
            {
                "document_id": document.id,
                "partner_id": partner.id,
                "role": "view",
                "expiration_date": "2000-01-01 00:00:00",
            }
        )

        done, more = Access._gc_expired()
        self.assertEqual(done, 1)
        self.assertFalse(more)
        self.assertFalse(
            document.access_ids.filtered(lambda a: a.partner_id == partner)
        )

    # ------------------------------------------------------------------
    # the tracking cron reference must not be load-bearing
    # ------------------------------------------------------------------

    def test_access_rights_update_survives_a_missing_cron(self):
        """Sharing keeps working when the tracking cron record is gone."""
        document = self.env["documents.document"].create(
            {"name": "shared.txt", "type": "binary"}
        )
        partner = self.env["res.partner"].create({"name": "new member"})
        self.env.ref("documents.ir_cron_documents_access_tracking").sudo().unlink()

        document.action_update_access_rights(
            partners={partner.id: ("view", False)},
        )

        self.assertEqual(
            document.access_ids.filtered(lambda a: a.partner_id == partner).role,
            "view",
        )

    # ------------------------------------------------------------------
    # inherited-access opt-out (guards the reordering fix's neighbours)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # a link completed one key at a time still reaches _create_document
    # ------------------------------------------------------------------

    def test_write_res_id_alone_links_the_pending_document(self):
        """`write` resolves the target off the record, not off the caller's vals.

        Binding an attachment is routinely done one key at a time -- the model
        does it itself in `_message_post_after_hook`. `create` already resolved
        the pair off the attachment; `write` read the raw `vals`, so completing a
        half-set link left `res_model=None` and `_create_document` matched
        nothing at all.
        """
        request_document = self.env["documents.document"].create(
            {"name": "awaiting content", "type": "binary"}
        )
        self.assertFalse(request_document.attachment_id)
        attachment = self.env["ir.attachment"].create(
            {"name": "late.txt", "raw": b"content", "res_model": "documents.document"}
        )
        self.assertFalse(request_document.attachment_id)

        attachment.write({"res_id": request_document.id})

        self.assertEqual(
            request_document.attachment_id,
            attachment,
            "writing the missing half of the link must bind the document",
        )

    def test_write_both_keys_still_links_the_pending_document(self):
        """The pre-existing spelling keeps working unchanged."""
        request_document = self.env["documents.document"].create(
            {"name": "awaiting content", "type": "binary"}
        )
        attachment = self.env["ir.attachment"].create(
            {"name": "late.txt", "raw": b"content"}
        )
        attachment.write(
            {"res_model": "documents.document", "res_id": request_document.id}
        )
        self.assertEqual(request_document.attachment_id, attachment)

    def test_write_unrelated_values_does_not_link_anything(self):
        """A write that says nothing about the link must not bind a document."""
        request_document = self.env["documents.document"].create(
            {"name": "awaiting content", "type": "binary"}
        )
        attachment = self.env["ir.attachment"].create(
            {"name": "late.txt", "raw": b"content", "res_model": "documents.document"}
        )
        attachment.write({"description": "renamed, not linked"})
        self.assertFalse(request_document.attachment_id)

    def test_write_a_batch_pointing_at_different_targets(self):
        """Each attachment resolves its own target, not the batch's first."""
        Document = self.env["documents.document"]
        first, second = Document.create(
            [
                {"name": "first", "type": "binary"},
                {"name": "second", "type": "binary"},
            ]
        )
        attachments = self.env["ir.attachment"].create(
            [
                {"name": "a.txt", "raw": b"a", "res_model": "documents.document"},
                {"name": "b.txt", "raw": b"b", "res_model": "documents.document"},
            ]
        )
        attachments[0].res_id = first.id
        attachments[1].res_id = second.id

        self.assertEqual(first.attachment_id, attachments[0])
        self.assertEqual(second.attachment_id, attachments[1])

    def test_create_in_folder_inherits_members_in_order(self):
        """A batch create inside a folder keeps vals/record alignment."""
        partner = self.env["res.partner"].create({"name": "folder member"})
        folder = self.env["documents.document"].create(
            {"name": "shared folder", "type": "folder"}
        )
        folder.action_update_access_rights(partners={partner.id: ("edit", False)})

        documents = self.env["documents.document"].create(
            [
                {"name": "inherits", "type": "binary", "folder_id": folder.id},
                {
                    "name": "opts out",
                    "type": "binary",
                    "folder_id": folder.id,
                    "access_ids": [Command.set([])],
                },
            ]
        )
        self.assertEqual(documents.mapped("name"), ["inherits", "opts out"])
        self.assertIn(partner, documents[0].access_ids.partner_id)
        self.assertNotIn(partner, documents[1].access_ids.filtered("role").partner_id)
