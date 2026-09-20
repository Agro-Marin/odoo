from types import SimpleNamespace

from odoo import Command
from odoo.service import security
from odoo.tests import TransactionCase, tagged


class _Session(dict):
    sid = "service_test_device" + "a" * 40

    def __init__(self, uid, trace):
        super().__init__()
        self.uid = uid
        self.trace = trace

    def _remove_old_sessions(self):
        pass

    def update_trace(self, request):
        return self.trace


@tagged("post_install", "-at_install")
class TestDeviceLogIsolation(TransactionCase):
    def test_failed_optional_write_preserves_the_request_transaction(self):
        import odoo.http

        user = self.env["res.users"].create(
            {
                "name": "Device isolation user",
                "login": "service_device_isolation",
                "group_ids": [Command.link(self.env.ref("base.group_user").id)],
            }
        )
        self.env.flush_all()
        self.cr.execute("""
            ALTER TABLE res_device_log ADD CONSTRAINT service_test_device_guard
            CHECK (session_identifier NOT LIKE 'service_test_device%')
        """)
        session = _Session(
            user.id,
            {
                "ip_address": "127.0.0.1",
                "platform": "probe",
                "browser": "probe",
                "first_activity": 1,
                "last_activity": 1,
            },
        )
        session.session_token = user._get_session_token(session.sid)
        request = SimpleNamespace(session=session, app=odoo.http.root)
        with self.assertLogs("odoo.service.security", level="WARNING"):
            self.assertTrue(security.is_session_valid(session, self.env, request))
        self.cr.execute("SELECT login FROM res_users WHERE id = %s", (user.id,))
        self.assertEqual(self.cr.fetchone(), ("service_device_isolation",))
        self.cr.execute(
            "SELECT count(*) FROM res_device_log WHERE session_identifier LIKE 'service_test_device%'"
        )
        self.assertEqual(self.cr.fetchone(), (0,))

    def test_unchanged_trace_does_not_open_a_savepoint(self):
        request = SimpleNamespace(session=_Session(self.env.uid, None))
        with self.assertQueryCount(0):
            self.env["res.device.log"]._update_device(request)
