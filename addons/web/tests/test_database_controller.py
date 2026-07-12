"""Tests for the database-manager master-password handling.

Covers the loopback gating of ``_handle_insecure_password``: the "auto-secure a
fresh install on first use" convenience must fire only for loopback callers, so
a remote request to an exposed database manager can never silently adopt an
attacker-chosen master password (locking the real admin out).
"""

from unittest.mock import MagicMock, patch

import odoo
from odoo.tests import TransactionCase, tagged

from odoo.addons.web.controllers.database import Database, _is_loopback


@tagged("web_unit", "database_manager")
class TestDatabaseMasterPassword(TransactionCase):
    """Loopback gating + audit logging of the default-master-password promotion."""

    def test_is_loopback(self):
        for addr in ("127.0.0.1", "127.0.0.5", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(_is_loopback(addr), addr)
        for addr in (
            "10.0.0.5",
            "203.0.113.7",
            "::ffff:203.0.113.7",
            "2001:db8::1",
            "",
            None,
            "not-an-ip",
            "localhost",  # a hostname, not an IP — must not slip through
        ):
            self.assertFalse(_is_loopback(addr), addr)

    def _promote_calls(self, *, insecure, remote_addr, master_pwd="new-strong-pw"):
        """Run ``_handle_insecure_password`` with the three dependencies stubbed
        and return the list of ``dispatch_rpc`` calls it made."""
        calls = []
        fake_request = MagicMock()
        fake_request.httprequest.remote_addr = remote_addr
        with (
            patch.object(
                odoo.tools.config, "verify_admin_password", return_value=insecure
            ),
            patch("odoo.addons.web.controllers.database.request", fake_request),
            patch(
                "odoo.addons.web.controllers.database.dispatch_rpc",
                side_effect=lambda *a, **k: calls.append(a),
            ),
        ):
            # self is unused by the method; pass a sentinel to avoid any
            # http.Controller instantiation concern.
            Database._handle_insecure_password(object(), master_pwd)
        return calls

    def test_promotes_from_loopback_when_insecure(self):
        calls = self._promote_calls(insecure=True, remote_addr="127.0.0.1")
        self.assertEqual(
            calls, [("db", "change_admin_password", ["admin", "new-strong-pw"])]
        )

    def test_promotes_from_ipv6_loopback(self):
        calls = self._promote_calls(insecure=True, remote_addr="::1")
        self.assertEqual(len(calls), 1)

    def test_refuses_promotion_from_remote_address(self):
        # Insecure default + a non-loopback caller: the operation may still
        # proceed (its own check_super runs against 'admin'), but the master
        # password must NOT be silently promoted to the submitted value.
        calls = self._promote_calls(insecure=True, remote_addr="203.0.113.7")
        self.assertEqual(calls, [])

    def test_refuses_promotion_when_remote_addr_unknown(self):
        # Fail closed: an unparseable/absent client address is not loopback.
        calls = self._promote_calls(insecure=True, remote_addr=None)
        self.assertEqual(calls, [])

    def test_noop_when_password_already_secure(self):
        # Password already changed away from the default: nothing to promote,
        # even from loopback.
        calls = self._promote_calls(insecure=False, remote_addr="127.0.0.1")
        self.assertEqual(calls, [])

    def test_noop_when_no_master_pwd_submitted(self):
        calls = self._promote_calls(
            insecure=True, remote_addr="127.0.0.1", master_pwd=""
        )
        self.assertEqual(calls, [])
