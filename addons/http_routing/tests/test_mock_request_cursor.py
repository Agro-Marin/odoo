from odoo.tests import HttpCase, tagged

from odoo.addons.http_routing.tests.common import MockRequest


@tagged("post_install", "-at_install")
class TestMockRequestCursor(HttpCase):
    def test_the_test_thread_may_open_a_cursor_under_its_own_mock_request(self):
        # `res.users._assert_can_auth` reads the login cooldown through its own
        # `registry.cursor()`; under a MockRequest the harness used to refuse it
        # for lacking the test-cursor cookie that only a server thread can be
        # asked for. web's TestReports authenticated inside one and died there.
        with MockRequest(self.env), self.registry.cursor() as cr:
            cr.execute("SELECT 1")
            self.assertEqual(cr.fetchone(), (1,))

    def test_a_mock_request_does_not_stop_a_login(self):
        admin = self.env.ref("base.user_admin")
        with MockRequest(self.env):
            session = self.authenticate(admin.login, admin.login)
        self.assertEqual(session.uid, admin.id)
