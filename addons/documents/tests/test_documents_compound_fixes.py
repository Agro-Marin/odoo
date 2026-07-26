from datetime import datetime
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import HttpCase, tagged
from odoo.tools import mute_logger

from .test_documents_common import GIF, TransactionCaseDocuments


@tagged("post_install", "-at_install")
class TestDocumentsCompoundFixes(TransactionCaseDocuments):
    """Regression tests for the compound correctness/security/perf fixes."""

    # -- documents.operation 'add' without attachment -----------------------
    def test_operation_add_without_attachment_message(self):
        wizard = self.env["documents.operation"].create({
            "operation": "add", "destination": "MY"})
        with self.assertRaises(UserError) as cm:
            wizard.action_confirm()
        self.assertEqual(str(cm.exception), "No attachment to add.")

    # -- mail.activity reschedule no longer needs write on the document -----
    def test_reschedule_request_activity_as_viewer(self):
        doc = self.env["documents.document"].create({
            "type": "binary", "name": "req", "datas": GIF,
            "owner_id": self.document_manager.id, "access_internal": "none"})
        requestee = self.portal_user.partner_id
        upload_type = self.env["mail.activity.type"].search(
            [("category", "=", "upload_file")], limit=1)
        self.assertTrue(upload_type)
        activity = self.env["mail.activity"].create({
            "activity_type_id": upload_type.id,
            "res_model_id": self.env.ref("documents.model_documents_document").id,
            "res_id": doc.id, "user_id": self.internal_user.id,
            "date_deadline": fields.Date.today()})
        doc.write({"requestee_partner_id": requestee.id,
                   "request_activity_id": activity.id})
        old_exp = fields.Datetime.now()
        access = self.env["documents.access"].sudo().create({
            "document_id": doc.id, "partner_id": requestee.id,
            "role": "view", "expiration_date": old_exp})
        doc.sudo().action_update_access_rights(
            partners={self.internal_user.partner_id: ("view", False)})
        self.assertEqual(doc.with_user(self.internal_user).user_permission, "view")

        new_date = fields.Date.add(fields.Date.today(), days=7)
        # Must not raise even though internal_user only has *view* on the doc.
        activity.with_user(self.internal_user).write({"date_deadline": new_date})
        self.assertEqual(
            access.expiration_date,
            datetime.combine(new_date, datetime.max.time()),
            "requestee access expiration should have been synced (in sudo)")

    # -- _upsert_last_access_date is now atomic & idempotent ----------------
    @mute_logger("odoo.sql_db")
    def test_upsert_last_access_date_idempotent(self):
        from odoo.addons.documents.controllers.documents import ShareRoute
        doc = self.document_gif
        env = self.env(user=self.internal_user)
        # ensure no pre-existing row
        self.env["documents.access"].sudo().search([
            ("document_id", "=", doc.id),
            ("partner_id", "=", self.internal_user.partner_id.id)]).unlink()
        created_first = ShareRoute._upsert_last_access_date(env, doc)
        self.assertTrue(created_first, "first access should report a creation")
        created_second = ShareRoute._upsert_last_access_date(env, doc)
        self.assertFalse(created_second, "second access should be an update, no error")
        rows = self.env["documents.access"].sudo().search([
            ("document_id", "=", doc.id),
            ("partner_id", "=", self.internal_user.partner_id.id)])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows.last_access_date)

    # -- ir.attachment._pdf_split bounds-checks client indices --------------
    def test_pdf_split_rejects_out_of_range_indices(self):
        with self.assertRaises(ValueError):
            self.env["ir.attachment"]._pdf_split(
                new_files=[{"name": "x", "new_pages": [
                    {"old_file_index": 99, "old_page_number": 1}]}],
                open_files=[])

    # -- _prepare_create_values batches shortcut read-access checks ---------
    def test_shortcut_access_check_is_batched(self):
        folder = self.env["documents.document"].create({
            "type": "folder", "name": "f", "owner_id": self.doc_user.id})
        targets = self.env["documents.document"].create([
            {"type": "binary", "name": f"t{i}", "datas": GIF,
             "folder_id": folder.id, "owner_id": self.doc_user.id}
            for i in range(5)])
        target_ids = set(targets.ids)
        sizes = []
        Doc = type(self.env["documents.document"])
        real = Doc.check_access

        def spy(recs, operation):
            if operation == "read" and recs._name == "documents.document" \
                    and set(recs.ids) & target_ids:
                sizes.append(len(recs))
            return real(recs, operation)

        with patch.object(Doc, "check_access", spy):
            self.env["documents.document"].create([
                {"type": "binary", "name": f"s{i}",
                 "shortcut_document_id": t.id, "folder_id": folder.id}
                for i, t in enumerate(targets)])
        # A single batched read-check over all 5 targets, not 5 singleton checks.
        self.assertIn(len(targets), sizes,
                      "shortcut targets should be access-checked in one batch")
        self.assertLess(sizes.count(1), len(targets),
                        "should not do one singleton check_access per shortcut")


@tagged("post_install", "-at_install")
class TestPublicFolderBatch(HttpCase, TransactionCaseDocuments):
    """The public folder page fetches every subfolder's children in one search
    (Fix H) and still renders each subfolder's document count correctly."""

    def test_nested_public_folder_renders_subfolder_counts(self):
        root = self.env["documents.document"].create({
            "type": "folder", "name": "shared root", "access_via_link": "view",
            "owner_id": self.doc_user.id})
        sub1, sub2 = self.env["documents.document"].create([
            {"type": "folder", "name": f"sub {n}", "folder_id": root.id,
             "access_via_link": "view", "owner_id": self.doc_user.id}
            for n in (1, 2)])
        # one file in sub1, two in sub2 (all link-visible)
        self.env["documents.document"].create(
            [{"type": "binary", "name": "s1-a", "datas": GIF,
              "folder_id": sub1.id, "access_via_link": "view",
              "owner_id": self.doc_user.id}]
            + [{"type": "binary", "name": f"s2-{i}", "datas": GIF,
                "folder_id": sub2.id, "access_via_link": "view",
                "owner_id": self.doc_user.id} for i in range(2)])
        res = self.url_open(root.access_url)
        res.raise_for_status()
        body = res.text
        self.assertIn("sub 1", body)
        self.assertIn("sub 2", body)
        # template renders "<count> documents" per subfolder (server-side)
        self.assertIn("1 documents", body)
        self.assertIn("2 documents", body)
