"""Regression tests for :mod:`portal.utils` credential validators.

Both validators are reached from public (``auth="public"``) chatter routes with
fully attacker-controlled ``thread_model`` / ``token`` / ``hash`` / ``pid``.
A ``mail.thread`` that does not carry a usable access token must make them
return ``False`` — never raise, which on a public route surfaces as HTTP 500
and leaks a stack trace / model internals.
"""

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
        """``res.partner`` is a ``mail.thread`` with no ``access_token`` field, so
        ``_sign_token`` raises ``NotImplementedError``. The validator must
        short-circuit to False instead of propagating it."""
        partner = self.env.ref("base.partner_root")
        self.assertFalse(validate_thread_with_hash_pid(partner, "deadbeef", partner.id))

    def test_token_on_tokenless_thread_returns_false(self):
        partner = self.env.ref("base.partner_root")
        self.assertFalse(validate_thread_with_token(partner, "some-token"))

    def test_token_with_empty_stored_value_does_not_raise(self):
        """A record whose token field exists but was never minted stores a falsy
        value; ``consteq(str, False)`` raises ``TypeError``. Guard against it."""

        class _FakeThread:
            # Field present (so the field-existence guard passes) but empty.
            _mail_post_token_field = "access_token"
            _fields = {"access_token": object()}

            def __getitem__(self, key):
                return False  # unshared record: token never minted

        self.assertFalse(validate_thread_with_token(_FakeThread(), "attacker-guess"))


class TestDocumentCheckAccess(TransactionCase):
    def test_returns_superuser_uid_recordset(self):
        """``_document_check_access`` must return a recordset carrying the
        SUPERUSER uid, not merely ``su=True`` on the acting user's uid.

        Regression guard for upstream fix 4d942852c82 (odoo/odoo#35030): since
        the sudo refactor, ``.sudo()`` keeps the current uid, so downstream code
        that re-derives ``self.env.uid`` (e.g. ``stock.quant`` on a portal user
        signing a ``sale_stock`` quote) crashes. Must be ``with_user``.
        """
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
            # The portal user can read its own partner (no token needed).
            document = portal_controller.CustomerPortal()._document_check_access(
                "res.partner", portal_user.partner_id.id
            )
        self.assertEqual(document.env.uid, SUPERUSER_ID)


@tagged("-at_install", "post_install")
class TestTokenValidatorHttp(HttpCase):
    @mute_logger("odoo.http")
    def test_chatter_init_hash_pid_tokenless_model_no_500(self):
        """``/portal/chatter_init`` with hash+pid on a tokenless ``mail.thread``
        used to raise ``NotImplementedError`` (HTTP 500 on a public route)."""
        result = self.make_jsonrpc_request(
            "/portal/chatter_init",
            params={
                "thread_model": "res.partner",
                "thread_id": self.env.ref("base.partner_root").id,
                "hash": "deadbeef",
                "pid": 1,
            },
        )
        # A well-formed Store payload proves the request completed (no 500).
        self.assertIsInstance(result, dict)
