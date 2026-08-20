"""The document <-> ir.attachment binding, and what it must not spawn.

Named for what it protects, not for the review that produced it.
"""

import base64
import io
from unittest.mock import patch

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from .test_documents_common import TransactionCaseDocuments


def _png(color):
    """Return a base64 PNG, i.e. content `image_process` can actually decode."""
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


class TestDocumentsContentAliases(TransactionCase):
    """``raw`` and ``datas`` are two writable aliases for the same bytes.

    ``documents.document.write`` used to branch on the literal ``"datas"``, so
    the two aliases behaved differently on every content-replacement concern.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Round4 User",
                "login": "round4_user",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )

    def _document(self, name, **vals):
        return (
            self.env["documents.document"]
            .with_user(self.user)
            .create({"name": name, "type": "binary", **vals})
        )

    def test_raw_write_keeps_previous_version(self):
        """Replacing content through ``raw`` must version like ``datas`` does.

        Otherwise the old file is overwritten in place and the document's
        history is silently destroyed -- the version is unrecoverable.
        """
        for field, payload in (("datas", base64.b64encode(b"v2")), ("raw", b"v2")):
            with self.subTest(field=field):
                document = self._document(f"versioned via {field}", raw=b"v1")
                original_attachment = document.attachment_id
                document.write({field: payload})
                document.invalidate_recordset()
                self.assertEqual(
                    len(document.previous_attachment_ids),
                    1,
                    f"writing {field!r} must archive the previous content",
                )
                self.assertEqual(bytes(document.attachment_id.raw), b"v2")
                self.assertEqual(document.attachment_id, original_attachment)

    def test_raw_write_creates_the_missing_attachment(self):
        """Uploading through ``raw`` on a pending request must not vanish.

        A document request has no ``attachment_id`` yet. Writing ``raw`` used to
        be routed to the related field of an *empty* ``ir.attachment`` recordset:
        no attachment was created, no error was raised, and the upload was lost.
        """
        for field, payload in (("datas", base64.b64encode(b"zz")), ("raw", b"zz")):
            with self.subTest(field=field):
                document = self._document(f"request via {field}")
                self.assertFalse(document.attachment_id)
                document.write({field: payload})
                document.invalidate_recordset()
                self.assertTrue(
                    document.attachment_id,
                    f"writing {field!r} must materialize the attachment",
                )
                self.assertEqual(bytes(document.attachment_id.raw), b"zz")

    def test_raw_write_logs_the_request_fulfilment(self):
        """Fulfilling a request must be traceable whichever alias is written."""
        for field, payload in (("datas", base64.b64encode(b"up")), ("raw", b"up")):
            with self.subTest(field=field):
                document = self._document(f"logged via {field}")
                before = len(document.message_ids)
                document.write({field: payload})
                document.invalidate_recordset()
                bodies = document.message_ids.mapped("body")
                self.assertGreater(len(document.message_ids), before)
                self.assertTrue(
                    any("Uploaded by" in (body or "") for body in bodies),
                    f"writing {field!r} must post the request-fulfilment message",
                )


@tagged("post_install", "-at_install")
class TestDocumentsAttachmentVals(TransactionCaseDocuments):
    """`create()` and `write()` must agree on what belongs to the attachment."""

    def test_create_and_write_route_the_same_keys(self):
        """Every attachment-related key is batched onto the attachment, both ways.

        `write` used to hardcode datas/raw/mimetype while `create` derived the
        set from the field definitions, so description/attachment_name/
        attachment_type fell back to the per-record related write on one path
        only.
        """
        document = self.env["documents.document"].create(
            {
                "name": "vals.txt",
                "folder_id": self.folder_a.id,
                "raw": b"created",
                "mimetype": "text/plain",
                "description": "made-on-create",
            }
        )
        self.assertEqual(document.attachment_id.description, "made-on-create")
        self.assertEqual(document.attachment_id.raw, b"created")

        document.write({"description": "set-on-write", "raw": b"written"})
        document.invalidate_recordset()
        self.assertEqual(document.attachment_id.description, "set-on-write")
        self.assertEqual(document.attachment_id.raw, b"written")

    def test_unknown_field_reports_as_an_invalid_field(self):
        """An unknown key must reach the ORM, not die on a raw KeyError.

        `create` indexed `self._fields[key]` while scanning vals, so a typo in a
        create() call surfaced as `KeyError` — an HTTP 500 instead of a
        validation error.
        """
        with self.assertRaises(ValueError):
            self.env["documents.document"].create(
                {
                    "name": "typo",
                    "type": "binary",
                    "definitely_not_a_field": 1,
                }
            )

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_derived_attachment_metadata_cannot_be_forged(self):
        """`checksum`/`index_content` always describe the stored bytes.

        They are `related="attachment_id.*"`, but `ir.attachment` strips them
        from its own vals, so a caller's value is discarded whichever route it
        takes. Pinned here because it is the reason `_pop_attachment_vals`
        deliberately does NOT carve them out: doing so would only move where
        they get dropped. Muted because the strip is reported now, and this is
        the caller it is meant to report.
        """
        document = self.env["documents.document"].create(
            {
                "name": "derived.txt",
                "folder_id": self.folder_a.id,
                "raw": b"real",
                "mimetype": "text/plain",
                "checksum": "forged",
                "index_content": "forged-index",
            }
        )
        document.invalidate_recordset()
        self.assertEqual(
            document.checksum,
            self.env["ir.attachment"]._content_checksum(b"real"),
            "checksum must describe the stored bytes, not what the caller sent",
        )
        self.assertNotEqual(document.index_content, "forged-index")


@tagged("post_install", "-at_install")
class TestDocumentsAttachmentTargetResolution(TransactionCaseDocuments):
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


@tagged("post_install", "-at_install")
class TestDocumentsAttachmentFiling(TransactionCase):
    def test_linking_to_a_record_does_not_spawn_a_second_document(self):
        """Re-binding the attachment must not re-enter document auto-creation.

        `mixin.documents` makes `ir.attachment.write` create a document for any
        attachment landing on a bridged model (hr.employee, project.project,
        product.template, account.move, ...). `_inverse_res_record` guards
        against that with `no_document` -- but set it on a value that a recordset
        union then discarded, because union keeps the *left* operand's
        environment and the accumulator it was unioned into carried the default
        context.

        Linking a document to such a record therefore created a *second*
        document for the same attachment: a duplicate where nothing stops it,
        and a `documents_document_attachment_unique` violation -- surfacing as
        HTTP 422 from `/documents/upload/` -- where the constraint does.
        """
        document = self.env["documents.document"].create(
            {"name": "linked.txt", "type": "binary", "raw": b"payload"}
        )
        partner = self.env["res.partner"].create({"name": "Link target"})

        attachment_class = type(self.env["ir.attachment"])
        with patch.object(
            attachment_class, "_create_document", autospec=True
        ) as create_document:
            document.write({"res_model": "res.partner", "res_id": partner.id})

        self.assertFalse(
            create_document.called,
            "re-binding a document's own attachment must not ask for a new "
            "document to be created for it",
        )
        self.assertEqual(document.attachment_id.res_model, "res.partner")
        self.assertEqual(document.attachment_id.res_id, partner.id)
        self.assertEqual(
            self.env["documents.document"].search_count(
                [("attachment_id", "=", document.attachment_id.id)]
            ),
            1,
            "exactly one document may reference the attachment",
        )

    def test_attachments_are_filed_once_per_target_record(self):
        """Filing is per linked record, not per attachment.

        ``_create_document`` takes a *recordset* and files it in a single
        ``documents.document`` create, but ``ir.attachment.create`` called it
        once per attachment -- so attaching fifteen files to one record paid
        fifteen folder resolutions and fifteen creates for work the method does
        in one pass. ``write`` had already been grouped by target; ``create``
        had not, which is also why the two disagreed about what ``vals`` the
        hook received.
        """
        partner = self.env["res.partner"].create({"name": "Batch target"})
        other = self.env["res.partner"].create({"name": "Other target"})
        attachment_class = type(self.env["ir.attachment"])

        with patch.object(
            attachment_class, "_create_document", autospec=True
        ) as create_document:
            self.env["ir.attachment"].create(
                [
                    {
                        "name": f"batch{index}.txt",
                        "raw": b"payload",
                        "res_model": "res.partner",
                        "res_id": (partner if index < 3 else other).id,
                    }
                    for index in range(4)
                ]
            )

        self.assertEqual(
            [call.args[1:] for call in create_document.call_args_list],
            [("res.partner", partner.id), ("res.partner", other.id)],
            "one call per distinct target, carrying the target explicitly",
        )
        self.assertEqual(
            [len(call.args[0]) for call in create_document.call_args_list],
            [3, 1],
            "each call must carry every attachment landing on that record",
        )

    def test_add_documents_attachment_copies_the_whole_set(self):
        """Copying to a record must pair each copy with its own origin.

        The copies used to be made one at a time, which defeated
        ``ir.attachment.copy``'s batching (it creates the rows in one pass and
        writes a shared store key once per group -- and content-addressed
        storage makes those groups real, as the two identical payloads below
        show). ``original_id`` is the one value that differs per copy, so the
        pairing is what a set-wide copy has to keep right; the whole method had
        no Python coverage, only a JS test that mocks the RPC.
        """
        Document = self.env["documents.document"]
        folder = Document.create({"name": "Media", "type": "folder"})
        documents = Document.create(
            [
                {"name": "one.txt", "folder_id": folder.id, "raw": b"same bytes"},
                {"name": "two.txt", "folder_id": folder.id, "raw": b"same bytes"},
                {"name": "three.txt", "folder_id": folder.id, "raw": b"other bytes"},
            ]
        )
        origins = documents.attachment_id
        self.assertEqual(
            len(set(origins[:2].mapped("store_fname"))),
            1,
            "identical payloads must already share one filestore key",
        )
        partner = self.env["res.partner"].create({"name": "Media target"})

        media = documents.add_documents_attachment(
            "res.partner", partner.id, is_public=True
        )

        self.assertEqual(len(media), 3)
        copies = self.env["ir.attachment"].browse([info["id"] for info in media])
        self.assertEqual(
            copies.mapped("original_id").ids,
            origins.ids,
            "each copy must point back at the attachment it was made from",
        )
        self.assertEqual(copies.mapped("res_model"), ["res.partner"] * 3)
        self.assertEqual(copies.mapped("res_id"), [partner.id] * 3)
        self.assertEqual(copies.mapped("public"), [True] * 3)
        self.assertTrue(
            all(copies.mapped("access_token")), "a public copy needs a token"
        )
        self.assertEqual(
            copies.mapped("raw"), [b"same bytes", b"same bytes", b"other bytes"]
        )

    def test_attachment_write_authorizes_before_mutating_the_document(self):
        """A refused attachment re-link must leave the target document untouched.

        ``ir.attachment.write`` filled ``documents.document.attachment_id`` (in
        sudo) *before* ``super().write()`` ran the ACL check on the new target,
        i.e. it mutated a record the caller had not been cleared for.
        """
        users = self.env["res.users"]
        group = Command.link(self.env.ref("documents.group_documents_user").id)
        owner = users.create(
            {"name": "R4 owner", "login": "r4_owner", "group_ids": [group]}
        )
        outsider = users.create(
            {"name": "R4 outsider", "login": "r4_outsider", "group_ids": [group]}
        )
        request_document = (
            self.env["documents.document"]
            .with_user(owner)
            .create(
                {
                    "name": "Private request",
                    "type": "binary",
                    "access_internal": "none",
                    "access_via_link": "none",
                }
            )
        )
        self.assertEqual(request_document.with_user(outsider).user_permission, "none")
        attachment = (
            self.env["ir.attachment"]
            .with_user(outsider)
            .create({"name": "outsider.txt", "raw": b"PWNED"})
        )

        # NOT `assertRaises`: it wraps the block in a savepoint, which rolls the
        # premature mutation back and makes the assertion below vacuous. The
        # point here is precisely that the side effect must not survive a
        # *swallowed* AccessError -- the case a caller that suppresses the error
        # (or any code continuing in the same transaction) would hit.
        raised = False
        try:
            attachment.with_user(outsider).write(
                {"res_model": "documents.document", "res_id": request_document.id}
            )
        except AccessError:
            raised = True
        self.assertTrue(raised, "re-linking to an unwritable document must be refused")

        self.env.flush_all()
        request_document.invalidate_recordset()
        self.assertFalse(
            request_document.attachment_id,
            "the refused write must not have attached anything",
        )
