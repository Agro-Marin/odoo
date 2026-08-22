import base64
import io
import json

from PIL import Image

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .test_documents_common import TransactionCaseDocuments


def _png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


@tagged("post_install", "-at_install")
class TestDocumentsThumbnail(TransactionCaseDocuments):
    def test_thumbnail_survives_a_web_save(self):
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


@tagged("post_install", "-at_install")
class TestDocumentsThumbnailRoutes(HttpCase, TransactionCaseDocuments):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("documents.group_documents_user").id,
        ]
        cls.manager = cls.env["res.users"].create(
            {
                "name": "audit_mgr",
                "login": "audit_mgr",
                "password": "audit_mgr",
                "email": "audit_mgr@t.test",
                "group_ids": [
                    Command.set(
                        groups + [cls.env.ref("documents.group_documents_manager").id]
                    )
                ],
            }
        )
        cls.uploader = cls.env["res.users"].create(
            {
                "name": "audit_up",
                "login": "audit_up",
                "password": "audit_up",
                "email": "audit_up@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        cls.victim = cls.env["res.users"].create(
            {
                "name": "audit_vic",
                "login": "audit_vic",
                "password": "audit_vic",
                "email": "audit_vic@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        cls.viewer = cls.env["res.users"].create(
            {
                "name": "audit_view",
                "login": "audit_view",
                "password": "audit_view",
                "email": "audit_view@t.test",
                "group_ids": [Command.set(groups)],
            }
        )
        Doc = cls.env["documents.document"]
        cls.folder = Doc.with_user(cls.manager).create(
            {"type": "folder", "name": "audit_folder", "user_folder_id": "COMPANY"}
        )
        cls.folder.action_update_access_rights(
            access_via_link="edit", partners={cls.uploader.partner_id: ("edit", False)}
        )
        cls.webp = Doc.with_user(cls.manager).create(
            {
                "type": "binary",
                "name": "audit.webp",
                "user_folder_id": "COMPANY",
                "datas": base64.b64encode(b"RIFF....WEBPVP8 "),
                "mimetype": "image/webp",
            }
        )
        cls.webp.action_update_access_rights(
            partners={cls.viewer.partner_id: ("view", False)}
        )

    def _post_thumbnail(self, payload):
        return self.url_open(
            f"/documents/document/{self.webp.id}/update_thumbnail",
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {"document_id": self.webp.id, "thumbnail": payload},
                }
            ),
        ).json()

    def test_s3_thumbnail_rejects_non_image(self):
        self.authenticate("audit_view", "audit_view")
        garbage = base64.b64encode(b"<svg onload=alert(1)>NOTIMAGE").decode()
        body = self._post_thumbnail(garbage)
        self.assertIn("error", body)
        self.assertFalse(self.webp.thumbnail)
        buffer = io.BytesIO()
        Image.new("RGB", (48, 48)).save(buffer, format="PNG")
        body = self._post_thumbnail(base64.b64encode(buffer.getvalue()).decode())
        self.assertNotIn("error", body)
        self.assertTrue(self.webp.thumbnail)
        self.assertTrue(base64.b64decode(self.webp.thumbnail).startswith(b"\x89PNG"))
