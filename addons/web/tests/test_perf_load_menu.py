from uuid import uuid4

from odoo.libs.json import dumps as json_dumps
from odoo.tests import common, tagged


@tagged("post_install", "-at_install", "web_perf", "web_menu")
class TestPerfSessionInfo(common.HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create(
            {
                "name": "Test Company",
            }
        )
        cls.user = common.new_test_user(
            cls.env,
            "session",
            email="session@in.fo",
            tz="UTC",
            company_id=cls.company.id,
        )

    def setUp(self):
        super().setUp()
        self.uid = self.user

    def test_performance_session_info(self):
        self.authenticate(self.user.login, "info")

        self.env.registry.clear_all_caches()
        with self.assertQueryCount(122):
            self.url_open(
                "/web/session/get_session_info",
                data=json_dumps(
                    {"jsonrpc": "2.0", "method": "call", "id": str(uuid4())}
                ),
                headers={"Content-Type": "application/json"},
            )

        with self.assertQueryCount(32):
            self.url_open(
                "/web/session/get_session_info",
                data=json_dumps(
                    {"jsonrpc": "2.0", "method": "call", "id": str(uuid4())}
                ),
                headers={"Content-Type": "application/json"},
            )

    def test_load_web_menus_perf(self):
        self.env.registry.clear_all_caches()
        self.env.invalidate_all()
        with self.assertQueryCount(57):
            self.env["ir.ui.menu"].load_web_menus(False)

        self.env.invalidate_all()
        with self.assertQueryCount(1):
            self.env["ir.ui.menu"].load_web_menus(False)

    def test_load_menus_perf(self):
        self.env.registry.clear_all_caches()
        self.env.invalidate_all()
        with self.assertQueryCount(57):
            self.env["ir.ui.menu"].load_menus(False)

        self.env.invalidate_all()
        with self.assertQueryCount(1):
            self.env["ir.ui.menu"].load_menus(False)

    def test_visible_menu_ids(self):
        self.env.registry.clear_all_caches()
        self.env.invalidate_all()
        with self.assertQueryCount(21):
            self.env["ir.ui.menu"]._visible_menu_ids()

        self.env.invalidate_all()
        with self.assertQueryCount(0):
            self.env["ir.ui.menu"]._visible_menu_ids()
