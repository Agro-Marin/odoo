import json
from io import BytesIO

from odoo import Command, http
from odoo.tests.common import HttpCase, RecordCapturer, tagged
from odoo.tools import mute_logger

from .test_documents_common import TEXT, TransactionCaseDocuments
from odoo.addons.base.tests.common import HttpCaseWithUserDemo
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestDocumentsPdfSplitTargets(HttpCaseWithUserDemo):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.splitter = mail_new_test_user(
            cls.env,
            login="round5_splitter",
            password="round5_splitter",
            groups="base.group_user,documents.group_documents_user",
        )

    def _split(self, document_id):
        return self.url_open(
            "/documents/pdf_split",
            data={
                "vals": "{}",
                "new_files": json.dumps(
                    [
                        {
                            "name": "out",
                            "new_pages": [
                                {
                                    "old_file_type": "document",
                                    "old_file_index": document_id,
                                    "old_page_number": 1,
                                }
                            ],
                        }
                    ]
                ),
                "csrf_token": http.Request.csrf_token(self),
            },
        )

    @mute_logger("odoo.http")
    def test_split_a_document_with_no_content(self):
        self.authenticate("round5_splitter", "round5_splitter")
        document = (
            self.env["documents.document"]
            .with_user(self.splitter)
            .create({"name": "awaiting.pdf", "type": "binary"})
        )
        self.assertFalse(document.attachment_id)
        self.assertEqual(self._split(document.id).status_code, 400)

    @mute_logger("odoo.http")
    def test_split_a_shortcut(self):
        self.authenticate("round5_splitter", "round5_splitter")
        Document = self.env["documents.document"].with_user(self.splitter)
        target = Document.create({"name": "real.pdf", "type": "binary", "datas": TEXT})
        shortcut = target.action_create_shortcut(location_user_folder_id="MY")
        self.assertFalse(shortcut.attachment_id)
        self.assertEqual(self._split(shortcut.id).status_code, 400)

    @mute_logger("odoo.http")
    def test_split_a_document_that_does_not_exist(self):
        self.authenticate("round5_splitter", "round5_splitter")
        missing_id = (
            self.env["documents.document"].search([], order="id desc", limit=1).id
        )
        self.assertIn(self._split(missing_id + 10_000).status_code, (400, 403, 404))


@tagged("post_install", "-at_install")
class TestDocumentsUploadRoute(HttpCase, TransactionCaseDocuments):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_internal = cls.env["res.users"].create(
            {
                "login": "plain_internal",
                "password": "plain_internal",
                "name": "Plain internal",
                "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
            }
        )
        cls.doc_user.password = "doc_user_pwd"

    def _upload(self, **fields):
        return self.url_open(
            "/documents/upload/",
            data={"csrf_token": http.Request.csrf_token(self), **fields},
            files={"ufile": ("hardening.txt", BytesIO(b"payload"), "text/plain")},
        )

    def test_root_upload_cannot_link_to_an_unwritable_record(self):
        self.authenticate("plain_internal", "plain_internal")
        company = self.env.ref("base.main_company")
        self.assertFalse(
            company.with_user(self.plain_internal).has_access("write"),
            "the fixture only means anything while the user cannot write it",
        )
        attachment_domain = [
            ("res_model", "=", "res.company"),
            ("res_id", "=", company.id),
        ]
        before = self.env["ir.attachment"].search_count(attachment_domain)
        with mute_logger("odoo.http"):
            response = self._upload(
                user_folder_id="MY",
                res_model="res.company",
                res_id=str(company.id),
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.env["ir.attachment"].search_count(attachment_domain),
            before,
            "nothing may be filed on a record the uploader cannot write",
        )

    def test_root_upload_still_works_without_a_linked_record(self):
        self.authenticate("plain_internal", "plain_internal")
        with RecordCapturer(self.env["documents.document"], []) as capture:
            response = self._upload(user_folder_id="MY")
            response.raise_for_status()
        document = capture.records.ensure_one()
        self.assertEqual(document.owner_id, self.plain_internal)
        self.assertFalse(document.res_model)

    def test_root_upload_may_link_to_a_writable_record(self):
        self.doc_user.group_ids += self.env.ref("base.group_partner_manager")
        self.authenticate("documents@example.com", "doc_user_pwd")
        partner = self.env["res.partner"].create({"name": "hardening target"})
        self.assertTrue(partner.with_user(self.doc_user).has_access("write"))
        with RecordCapturer(self.env["documents.document"], []) as capture:
            response = self._upload(
                user_folder_id="MY",
                res_model="res.partner",
                res_id=str(partner.id),
            )
            response.raise_for_status()
        document = capture.records.ensure_one()
        self.assertEqual(document.res_model, "res.partner")
        self.assertEqual(document.res_id, partner.id)


@tagged("post_install", "-at_install")
class TestDocumentsPdfSplitInput(TransactionCaseDocuments):
    def test_pdf_split_rejects_out_of_range_indices(self):
        with self.assertRaises(ValueError):
            self.env["ir.attachment"]._pdf_split(
                new_files=[
                    {
                        "name": "x",
                        "new_pages": [{"old_file_index": 99, "old_page_number": 1}],
                    }
                ],
                open_files=[],
            )
