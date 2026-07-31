"""Shortcuts: what they mirror, what they may not widen.

Named for what it protects, not for the review that produced it.
"""

import base64
import io
from unittest.mock import patch

from PIL import Image

from odoo.exceptions import AccessError
from odoo.tests.common import tagged, users

from .test_documents_common import GIF, TEXT, TransactionCaseDocuments


def _png(color):
    """Return a base64 PNG, i.e. content `image_process` can actually decode."""
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


@tagged("post_install", "-at_install")
class TestDocumentsShortcutFields(TransactionCaseDocuments):
    """A shortcut derives what it can; only the rest is copied from the target."""

    def test_copy_fields_hold_nothing_the_computes_already_resolve(self):
        copy_fields = self.env["documents.document"]._get_shortcuts_copy_fields()
        fields = self.env["documents.document"]._fields
        redundant = sorted(
            name
            for name in copy_fields
            if fields[name].compute and fields[name].readonly
        )
        self.assertFalse(
            redundant,
            "a readonly computed field cannot be seeded through create(): the "
            "value is discarded, so listing it here is dead code",
        )

    def test_shortcut_derives_its_own_name_size_and_extension(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "target.txt",
                "raw": b"a" * 42,
                "mimetype": "text/plain",
            }
        )
        target = self.env["documents.document"].create(
            {
                "name": "target.txt",
                "folder_id": self.folder_a.id,
                "attachment_id": attachment.id,
            }
        )
        shortcut = target.action_create_shortcut(
            location_user_folder_id=str(self.folder_a.id)
        )
        shortcut.invalidate_recordset()

        self.assertEqual(shortcut.name, target.name)
        self.assertEqual(shortcut.file_size, target.file_size)
        self.assertEqual(shortcut.file_extension, target.file_extension)
        self.assertEqual(shortcut.type, target.type)

    def test_folder_shortcut_keeps_the_target_type(self):
        """`type` is readonly but NOT computed, so it does land — and it must:
        `_check_shortcut_fields` requires a shortcut to share its target's type.
        """
        target = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "folder target",
            }
        )
        shortcut = target.action_create_shortcut(
            location_user_folder_id=str(self.folder_a.id)
        )
        self.assertEqual(shortcut.type, "folder")


@tagged("post_install", "-at_install")
class TestDocumentsShortcutAccess(TransactionCaseDocuments):
    def test_f2_shortcut_create_inherits_target_access(self):
        """A plain create() of a shortcut takes its access from the target."""
        target = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": GIF,
                "name": "audit3 private target",
                "folder_id": self.folder_a.id,
                "owner_id": self.doc_user.id,
                "access_via_link": "none",
                "access_internal": "none",
                "is_access_via_link_hidden": True,
            }
        )
        public_folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 public folder",
                "owner_id": self.doc_user.id,
                "access_via_link": "view",
                "access_internal": "view",
                "is_access_via_link_hidden": False,
            }
        )
        shortcut = self.env["documents.document"].create(
            {
                "shortcut_document_id": target.id,
                "folder_id": public_folder.id,
            }
        )
        # Must not have been published by the folder it was dropped into.
        self.assertEqual(shortcut.access_via_link, "none")
        self.assertEqual(shortcut.access_internal, "none")
        self.assertTrue(shortcut.is_access_via_link_hidden)

        # Explicit values still win over the target.
        explicit = self.env["documents.document"].create(
            {
                "shortcut_document_id": target.id,
                "folder_id": public_folder.id,
                "access_internal": "edit",
            }
        )
        self.assertEqual(explicit.access_internal, "edit")
        self.assertEqual(explicit.access_via_link, "none")

        # Non-shortcut documents keep inheriting from their folder.
        plain = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 plain",
                "folder_id": public_folder.id,
            }
        )
        self.assertEqual(plain.access_via_link, "view")
        self.assertEqual(plain.access_internal, "view")

    def test_f3_shortcut_to_company_root_requires_manager(self):
        """A non-manager cannot inject a folder at the Company root."""
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 source folder",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
            }
        )
        with self.assertRaises(AccessError):
            folder.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertFalse(
            self.env["documents.document"].search_count(
                [
                    ("shortcut_document_id", "=", folder.id),
                    ("folder_id", "=", False),
                    ("owner_id", "=", False),
                ]
            )
        )

        # A manager may.
        shortcut = folder.with_user(self.document_manager).action_create_shortcut(
            "COMPANY"
        )
        self.assertTrue(shortcut._is_company_root_folder())

    def test_f3_shortcut_to_file_at_company_root_still_allowed(self):
        """Only the folder case is manager-only; files stay allowed."""
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 shortcut file",
                "owner_id": self.doc_user_2.id,
            }
        )
        shortcut = doc.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertEqual(shortcut.shortcut_document_id, doc)
        self.assertFalse(shortcut._is_company_root_folder())

    def test_f3_shortcut_check_runs_before_sudo(self):
        """The check must happen before the internal sudo(), not inside create.

        `create`'s manager guard is intentionally sudo-bypassable (see
        `test_mail_gateway.test_alias_access`), so `action_create_shortcut`,
        which sudoes on the user's behalf, has to enforce it itself.
        """
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 sudo probe folder",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
            }
        )
        before = self.env["documents.document"].search_count(
            [("folder_id", "=", False), ("owner_id", "=", False)]
        )
        with self.assertRaises(AccessError):
            folder.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertEqual(
            self.env["documents.document"].search_count(
                [("folder_id", "=", False), ("owner_id", "=", False)]
            ),
            before,
            "a company root folder was created despite the refusal",
        )

    # -- _prepare_create_values batches shortcut read-access checks ---------
    def test_shortcut_access_check_is_batched(self):
        folder = self.env["documents.document"].create(
            {"type": "folder", "name": "f", "owner_id": self.doc_user.id}
        )
        targets = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": f"t{i}",
                    "datas": GIF,
                    "folder_id": folder.id,
                    "owner_id": self.doc_user.id,
                }
                for i in range(5)
            ]
        )
        target_ids = set(targets.ids)
        sizes = []
        Doc = type(self.env["documents.document"])
        real = Doc.check_access

        def spy(recs, operation):
            if (
                operation == "read"
                and recs._name == "documents.document"
                and set(recs.ids) & target_ids
            ):
                sizes.append(len(recs))
            return real(recs, operation)

        with patch.object(Doc, "check_access", spy):
            self.env["documents.document"].create(
                [
                    {
                        "type": "binary",
                        "name": f"s{i}",
                        "shortcut_document_id": t.id,
                        "folder_id": folder.id,
                    }
                    for i, t in enumerate(targets)
                ]
            )
        # A single batched read-check over all 5 targets, not 5 singleton checks.
        self.assertIn(
            len(targets),
            sizes,
            "shortcut targets should be access-checked in one batch",
        )
        self.assertLess(
            sizes.count(1),
            len(targets),
            "should not do one singleton check_access per shortcut",
        )


@tagged("post_install", "-at_install")
class TestDocumentsShortcutAsParent(TransactionCaseDocuments):
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
