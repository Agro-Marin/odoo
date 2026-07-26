import base64
import io
import json
from unittest.mock import patch

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .test_documents_common import TransactionCaseDocuments
from odoo.addons.mail.tools import link_preview


@tagged("post_install", "-at_install")
class TestDocumentsAuditFixes(TransactionCaseDocuments):
    """Regression tests for the documents security/correctness audit fixes."""

    # -- S1a: share users cannot inject broadly-accessible root documents ----
    def test_s1a_share_user_cannot_create_root_document(self):
        Document = self.env["documents.document"].with_user(self.portal_user)
        with self.assertRaises(AccessError):
            Document.create(
                {
                    "name": "injected",
                    "type": "binary",
                    "folder_id": False,
                    "owner_id": False,
                    "company_id": False,
                    "access_internal": "edit",
                }
            )

    def test_s1a_share_user_create_does_not_elevate_access(self):
        # A share user creating inside a folder they may reach must not be able
        # to set access_internal/access_via_link (they are stripped / inherited).
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "shared to portal",
                "access_via_link": "edit",
                "access_internal": "none",
            }
        )
        folder.action_update_access_rights(
            partners={self.portal_user.partner_id: ("edit", False)}
        )
        # An explicit access_internal='edit' must not survive; the create either
        # inherits the folder value or is refused, but never elevates.
        try:
            doc = (
                self.env["documents.document"]
                .with_user(self.portal_user)
                .create(
                    {
                        "name": "child",
                        "type": "url",
                        "url": "https://example.com",
                        "folder_id": folder.id,
                        "owner_id": False,
                        "access_internal": "edit",
                    }
                )
            )
        except AccessError:
            return  # refused outright is acceptable
        self.assertNotEqual(doc.access_internal, "edit")

    # -- C5: members added before the caller's own access is downgraded -------
    def test_c5_member_kept_on_internal_downgrade(self):
        # A manager whose edit right on a company-root document comes from
        # access_internal downgrades it to 'none' while adding a member in the
        # same call: the member must still be granted.
        doc = (
            self.env["documents.document"]
            .with_user(self.document_manager)
            .create({"type": "binary", "name": "c5", "user_folder_id": "COMPANY"})
        )
        doc.with_user(self.document_manager).action_update_access_rights(
            access_internal="none",
            partners={self.internal_user.partner_id: ("view", False)},
        )
        # Read in sudo: the manager just removed their own (internal) access.
        member = doc.sudo().access_ids.filtered(
            lambda a: a.partner_id == self.internal_user.partner_id and a.role
        )
        self.assertTrue(member, "member grant must survive the internal downgrade")
        self.assertEqual(member.role, "view")

    def test_c5_sharing_wizard_no_crash_on_self_access_loss(self):
        doc = (
            self.env["documents.document"]
            .with_user(self.document_manager)
            .create({"type": "binary", "name": "c5w", "user_folder_id": "COMPANY"})
        )
        Sharing = self.env["documents.sharing"].with_user(self.document_manager)
        wizard = Sharing.browse(Sharing.action_open(doc.ids)["res_id"])
        wizard.write({"access_internal": "write_none"})
        # Must not raise AccessError while rebuilding the (now inaccessible) wizard.
        result = wizard.action_update_rights()
        self.assertIsInstance(result, dict)

    # -- S4: res_name must not leak past the linked record's ACL -------------
    def test_s4_res_name_hidden_for_inaccessible_record(self):
        secret = self.env["res.partner"].create({"name": "SECRET_AUDIT_PARTNER"})
        # Global rule (no groups) -> ANDed for every non-superuser, so the
        # linked record is genuinely unreadable by the internal user.
        self.env["ir.rule"].create(
            {
                "name": "hide secret audit partner",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "domain_force": "[('name', '!=', 'SECRET_AUDIT_PARTNER')]",
                "perm_read": True,
                "perm_write": True,
                "perm_create": False,
                "perm_unlink": False,
            }
        )
        doc = (
            self.env["documents.document"]
            .with_user(self.document_manager)
            .create(
                {
                    "type": "binary",
                    "name": "linked",
                    "user_folder_id": "COMPANY",
                    "res_model": "res.partner",
                    "res_id": secret.id,
                }
            )
        )
        doc.action_update_access_rights(access_internal="view")
        self.env.invalidate_all()
        # Sanity: the internal user genuinely cannot read the linked record
        # (record rule enforced on actual read, not on has_access/model ACL).
        with self.assertRaises(AccessError):
            secret.with_user(self.internal_user).read(["name"])
        self.assertNotEqual(
            doc.with_user(self.internal_user).res_name,
            "SECRET_AUDIT_PARTNER",
            "res_name must not leak the name of an inaccessible linked record",
        )

    # -- P1: URL preview fetched asynchronously, never in the write txn -------
    def test_p1_url_preview_is_deferred(self):
        calls = []

        def spy(url, session, *args, **kwargs):
            calls.append(url)
            return {"og_title": "Real Title", "og_image": "https://img/x.png"}

        with patch.object(link_preview, "get_link_preview_from_url", spy):
            doc = self.env["documents.document"].create(
                {"type": "url", "url": "https://example.com/probe"}
            )
            # Reading the stored fields must not trigger a synchronous fetch.
            doc.name  # noqa: B018
            doc.url_preview_image  # noqa: B018
            self.assertEqual(calls, [], "URL preview must not be fetched synchronously")
            self.assertTrue(doc.url_preview_pending)
            self.assertEqual(doc.name, "https://example.com/probe")

            self.env["documents.document"]._cron_update_url_preview()

        # The cron processes every pending URL document (there may be others,
        # e.g. from demo data); assert ours was fetched and updated.
        self.assertIn("https://example.com/probe", calls)
        self.assertFalse(doc.url_preview_pending)
        self.assertEqual(doc.name, "Real Title")
        self.assertEqual(doc.url_preview_image, "https://img/x.png")


@tagged("post_install", "-at_install")
class TestDocumentsAuditFixesHttp(HttpCase):
    """HTTP-layer regression tests for the audit fixes."""

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
        # jsonrpc surfaces the BadRequest as an error; nothing is stored.
        self.assertIn("error", body)
        self.assertFalse(self.webp.thumbnail)
        # A real image is accepted and re-encoded to a clean PNG.
        buffer = io.BytesIO()
        Image.new("RGB", (48, 48)).save(buffer, format="PNG")
        body = self._post_thumbnail(base64.b64encode(buffer.getvalue()).decode())
        self.assertNotIn("error", body)
        self.assertTrue(self.webp.thumbnail)
        self.assertTrue(base64.b64decode(self.webp.thumbnail).startswith(b"\x89PNG"))

    def test_c3_bad_member_id_is_bad_request(self):
        res = self.url_open(
            f"/documents/{self.folder.access_token}?member_id=NOTANUMBER",
            allow_redirects=False,
        )
        self.assertEqual(res.status_code, 400)

    def test_c4_pdf_first_page_rejects_non_pdf(self):
        res = self.url_open(
            f"/documents/content/pdf_first_page/{self.webp.access_token}",
            allow_redirects=False,
        )
        self.assertIn(res.status_code, (400, 404))
