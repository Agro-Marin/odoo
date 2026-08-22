from unittest.mock import patch

from odoo import SUPERUSER_ID
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.portal.controllers import portal as portal_controller
from odoo.addons.portal.utils import (
    validate_thread_with_hash_pid,
    validate_thread_with_token,
)


class TestTokenValidatorUnit(TransactionCase):
    def test_hash_pid_on_tokenless_thread_returns_false(self):
        partner = self.env.ref("base.partner_root")
        self.assertFalse(validate_thread_with_hash_pid(partner, "deadbeef", partner.id))

    def test_token_on_tokenless_thread_returns_false(self):
        partner = self.env.ref("base.partner_root")
        self.assertFalse(validate_thread_with_token(partner, "some-token"))

    def test_token_with_empty_stored_value_does_not_raise(self):

        class _FakeThread:
            _mail_post_token_field = "access_token"
            _fields = {"access_token": object()}

            def __getitem__(self, key):
                return False

        self.assertFalse(validate_thread_with_token(_FakeThread(), "attacker-guess"))


class TestDocumentCheckAccess(TransactionCase):
    def test_returns_superuser_uid_recordset(self):
        portal_user = self.env["res.users"].create(
            {
                "name": "doc-check portal",
                "login": "doc_check_portal",
                "password": "doc_check_portal",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        env_portal = self.env(user=portal_user)

        class _Req:
            env = env_portal

        with patch.object(portal_controller, "request", _Req()):
            document = portal_controller.CustomerPortal()._document_check_access(
                "res.partner", portal_user.partner_id.id
            )
        self.assertEqual(document.env.uid, SUPERUSER_ID)


@tagged("-at_install", "post_install")
class TestTokenValidatorHttp(HttpCase):
    @mute_logger("odoo.http")
    def test_chatter_init_hash_pid_tokenless_model_no_500(self):
        result = self.make_jsonrpc_request(
            "/portal/chatter_init",
            params={
                "thread_model": "res.partner",
                "thread_id": self.env.ref("base.partner_root").id,
                "hash": "deadbeef",
                "pid": 1,
            },
        )
        self.assertIsInstance(result, dict)
