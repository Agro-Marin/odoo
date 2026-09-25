from datetime import timedelta
from urllib.parse import urlparse

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import SQL

from odoo.addons.base.models.access_link import hash_token
from odoo.addons.mail.tests.common import mail_new_test_user

LEGACY_TOKEN = "Qx7kP2mN9vR4tY6wZ1aB3c"


@tagged("post_install", "-at_install", "access_link")
class TestDocumentLinks(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = mail_new_test_user(
            cls.env,
            login="links_owner",
            groups="document.group_documents_user",
            name="Links Owner",
        )
        cls.stranger = mail_new_test_user(
            cls.env, login="links_stranger", groups="base.group_user", name="Stranger"
        )
        cls.reader = mail_new_test_user(
            cls.env, login="links_reader", groups="base.group_user", name="Reader"
        )
        Document = cls.env["document.document"].with_user(cls.owner)
        cls.file = Document.create(
            {
                "name": "report.txt",
                "type": "binary",
                "raw": b"quarterly figures",
                "mimetype": "text/plain",
            }
        )
        cls.file.action_update_access_rights(
            partners={cls.reader.partner_id: ("view", False)}
        )
        cls.other = Document.create(
            {
                "name": "other.txt",
                "type": "binary",
                "raw": b"other",
                "mimetype": "text/plain",
            }
        )

    def _content(self, access_token, login=None):
        self.authenticate(login, login)
        return self.url_open(f"/documents/content/{access_token}")

    def _share(self, role="view"):
        self.file.with_user(self.owner).action_update_access_rights(
            access_via_link=role
        )
        self.file.invalidate_recordset(["access_token", "link_date_to"])
        return self.file.with_user(self.owner).access_token

    def test_a_document_without_a_link_opens_for_its_readers_only(self):
        address = self.file.with_user(self.owner).access_token
        self.assertEqual(address, f"o{self.file.id:x}")
        self.assertEqual(self._content(address, "links_reader").status_code, 200)
        self.assertEqual(self._content(address, "links_stranger").status_code, 404)
        self.assertEqual(self._content(address).status_code, 404)

    def test_the_link_is_an_access_link_that_follows_the_setting(self):
        url = self._share("view")
        token = url.rpartition("o")[0]
        link = (
            self.env["access.link"]
            .sudo()
            .search(
                [("res_model", "=", "document.document"), ("res_id", "=", self.file.id)]
            )
        )
        self.assertEqual(link.mapped("role"), ["view"])
        self.assertEqual(link.token_hint, token[:4])
        self.assertEqual(self._content(url).status_code, 200)

        self.assertEqual(self._share("edit"), url, "raising the role keeps the URL")
        self.assertEqual(link.role, "edit")

        self._share("none")
        self.assertEqual(link.state, "revoked")
        self.assertEqual(self._content(url).status_code, 404)

        again = self._share("view")
        self.assertNotEqual(again, url, "a link turned on again is a new link")
        self.assertEqual(self._content(again).status_code, 200)

    def test_a_link_shared_by_hand_expires_in_30_days_and_the_dialog_sets_it(self):
        self._share("view")
        self.assertAlmostEqual(
            self.file.link_date_to,
            fields.Datetime.now() + timedelta(days=30),
            delta=timedelta(minutes=5),
        )
        later = fields.Datetime.now() + timedelta(days=200)
        sharing = (
            self.env["document.sharing"]
            .with_user(self.owner)
            .action_open(self.file.ids)
        )
        wizard = (
            self.env["document.sharing"].with_user(self.owner).browse(sharing["res_id"])
        )
        wizard.link_date_to = later
        self.assertTrue(wizard.is_access_modified)
        wizard.action_update_rights()
        self.file.invalidate_recordset(["link_date_to"])
        self.assertEqual(self.file.link_date_to, later.replace(microsecond=0))

    def test_a_document_created_shared_keeps_its_link_a_year(self):
        document = (
            self.env["document.document"]
            .sudo()
            .create(
                {"name": "payslip.pdf", "type": "binary", "access_via_link": "view"}
            )
        )
        self.assertAlmostEqual(
            document.link_date_to,
            fields.Datetime.now() + timedelta(days=365),
            delta=timedelta(minutes=5),
        )

    def test_an_expired_link_opens_nothing(self):
        url = self._share("view")
        self.env["access.link"].sudo().search(
            [("res_model", "=", "document.document"), ("res_id", "=", self.file.id)]
        ).date_to = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(self._content(url).status_code, 404)

    def test_a_token_from_before_the_upgrade_still_opens_the_document(self):
        self._share("view")
        self.env.cr.execute(
            SQL(
                """
                INSERT INTO access_link (res_model, res_id, role, audience,
                       token_hash, token_hint, date_to, cause, legacy_source,
                       use_count, expiry_waived)
                VALUES ('document.document', %s, 'view', 'anyone', %s, %s,
                        now() + interval '365 days', 'migration',
                        'document.document.document_token', 0, false)
                """,
                self.file.id,
                hash_token(LEGACY_TOKEN),
                LEGACY_TOKEN[:4],
            )
        )
        legacy_url = f"{LEGACY_TOKEN}o{self.file.id:x}"
        self.assertEqual(self._content(legacy_url).status_code, 200)
        self.assertEqual(
            self._content(f"{LEGACY_TOKEN}o{self.other.id:x}").status_code, 404
        )
        self._share("none")
        self.assertEqual(self._content(legacy_url).status_code, 404)

    def test_a_signed_in_visitor_holding_only_the_link_gets_the_shared_page(self):
        url = self._share("view")
        self.authenticate("links_stranger", "links_stranger")
        response = self.url_open(f"/odoo/documents/{url}", allow_redirects=False)
        self.assertEqual(
            urlparse(response.headers["Location"]).path, f"/documents/{url}"
        )
        self.assertEqual(self.url_open(f"/documents/{url}").status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(self.file.with_user(self.stranger).user_permission, "none")
        self.assertFalse(
            self.env["document.document"]
            .with_user(self.stranger)
            .search([("id", "=", self.file.id)])
        )
        link = (
            self.env["access.link"]
            .sudo()
            .search(
                [("res_model", "=", "document.document"), ("res_id", "=", self.file.id)]
            )
        )
        self.assertGreaterEqual(link.use_count, 1, "the visit is the link's use")
