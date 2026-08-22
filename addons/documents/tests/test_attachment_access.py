import base64

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase


class testAttachmentAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create(
            {
                "name": "foo",
                "login": "foo",
                "email": "foo@bar.com",
                "group_ids": [
                    (6, 0, [cls.env.ref("documents.group_documents_user").id])
                ],
            }
        )
        folder = cls.env["documents.document"].create(
            {"type": "folder", "name": "foo", "access_internal": "edit"}
        )
        cls.document_defaults = {
            "folder_id": folder.id,
        }

    def test_user_document_attachment_without_res_fields(self):
        env_user = self.env(user=self.user)
        attachment = env_user["ir.attachment"].create(
            {"name": "foo", "datas": base64.b64encode(b"foo")}
        )
        document = env_user["documents.document"].create(
            {"attachment_id": attachment.id, **self.document_defaults}
        )
        self.assertEqual(base64.b64decode(document.datas), b"foo")
        attachment_2 = env_user["ir.attachment"].create(
            {"name": "foo", "datas": base64.b64encode(b"bar")}
        )
        document.write({"attachment_id": attachment_2.id})
        self.assertEqual(base64.b64decode(document.datas), b"bar")

    def test_user_document_attachment_without_res_fields_created_by_admin(self):
        attachment = self.env["ir.attachment"].create(
            {"name": "foo", "datas": base64.b64encode(b"foo")}
        )
        document = self.env["documents.document"].create(
            {"attachment_id": attachment.id, **self.document_defaults}
        )
        self.assertEqual(attachment.res_model, "documents.document")
        self.assertEqual(attachment.res_id, document.id)

        self.env.invalidate_all()
        self.assertEqual(
            base64.b64decode(attachment.with_user(self.user).datas), b"foo"
        )
        self.assertEqual(base64.b64decode(document.with_user(self.user).datas), b"foo")

        attachment = self.env["ir.attachment"].create(
            {"name": "bar", "datas": base64.b64encode(b"bar")}
        )
        document.write({"attachment_id": attachment.id})
        attachment.res_model = attachment.res_id = False
        self.assertFalse(attachment.res_model)
        self.assertFalse(attachment.res_id)

        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.assertEqual(
                base64.b64decode(attachment.with_user(self.user).datas), b"bar"
            )
        self.assertEqual(base64.b64decode(document.with_user(self.user).datas), b"bar")

    def test_user_read_unallowed_attachment(self):
        autovacuum_job = self.env.ref("base.autovacuum_job")
        attachment_forbidden = self.env["ir.attachment"].create(
            {
                "name": "foo",
                "datas": base64.b64encode(b"foo"),
                "res_model": autovacuum_job._name,
                "res_id": autovacuum_job.id,
            }
        )
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            _ = attachment_forbidden.with_user(self.user).datas
        with self.assertRaises(AccessError):
            document = (
                self.env["documents.document"]
                .with_user(self.user)
                .create(
                    {
                        "attachment_id": attachment_forbidden.id,
                        **self.document_defaults,
                    }
                )
            )
            _ = document.datas

        attachment_tmp = (
            self.env["ir.attachment"]
            .with_user(self.user)
            .create(
                {
                    "name": "bar",
                    "datas": base64.b64encode(b"bar"),
                }
            )
        )
        document = (
            self.env["documents.document"]
            .with_user(self.user)
            .create(
                {
                    "attachment_id": attachment_tmp.id,
                    **self.document_defaults,
                }
            )
        )
        with self.assertRaises(AccessError):
            document.write({"attachment_id": attachment_forbidden.id})
            _ = document.datas

    def test_create_shortcut(self):
        doc = self.env["documents.document"].create(
            {"name": "secret", "access_internal": "none"}
        )

        with self.assertRaises(AccessError):
            self.env["documents.document"].with_user(self.user).create(
                {"shortcut_document_id": doc.id}
            )
