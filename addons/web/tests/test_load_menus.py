import json
import re

from odoo import Command, api, tools
from odoo.tests.common import HttpCase, tagged


@tagged("web_http", "web_menu")
class LoadMenusTests(HttpCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.menu = self.env["ir.ui.menu"].create(
            {
                "name": "root menu (test)",
                "parent_id": False,
            }
        )
        self.action = self.env["ir.actions.act_window"].create(
            {
                "name": "action (test)",
                "res_model": "res.users",
                "view_ids": [Command.create({"view_mode": "form"})],
            }
        )
        self.menu_child = self.env["ir.ui.menu"].create(
            {
                "name": "child menu (test)",
                "parent_id": self.menu.id,
                "action": f"{self.action._name},{self.action.id}",
            }
        )

        menus = self.menu + self.menu_child

        origin_search_fetch = self.env.registry["ir.ui.menu"].search_fetch

        @api.model
        def search_fetch(self, domain, *args, **kwargs):
            return origin_search_fetch(
                self, domain + [("id", "in", menus.ids)], *args, **kwargs
            )

        self.patch(self.env.registry["ir.ui.menu"], "search_fetch", search_fetch)
        self.authenticate("admin", "admin")

    def test_load_menus(self):
        menu_loaded = self.url_open("/web/webclient/load_menus")
        expected = {
            str(self.menu.id): {
                "actionID": self.action.id,
                "actionModel": "ir.actions.act_window",
                "actionPath": False,
                "appID": self.menu.id,
                "children": [self.menu_child.id],
                "id": self.menu.id,
                "name": "root menu (test)",
                "webIcon": False,
                "webIconData": "/web/static/img/default_icon_app.png",
                "webIconDataMimetype": False,
                "xmlid": "",
            },
            str(self.menu_child.id): {
                "actionID": self.action.id,
                "actionModel": "ir.actions.act_window",
                "actionPath": False,
                "appID": self.menu.id,
                "children": [],
                "id": self.menu_child.id,
                "name": "child menu (test)",
                "webIcon": False,
                "webIconData": False,
                "webIconDataMimetype": False,
                "xmlid": "",
            },
            "root": {
                "actionID": False,
                "actionModel": False,
                "actionPath": False,
                "appID": False,
                "backgroundImage": None,
                "children": [self.menu.id],
                "id": "root",
                "name": "root",
                "webIcon": None,
                "webIconData": None,
                "webIconDataMimetype": None,
                "xmlid": "",
            },
        }

        self.assertDictEqual(
            menu_loaded.json(),
            expected,
            "load_menus didn't return the expected value",
        )

    def test_load_menus_conditional(self):
        res = self.url_open("/web/webclient/load_menus")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")
        current_hash = res.headers.get("X-Menus-Hash")
        self.assertTrue(current_hash, "200 response must expose X-Menus-Hash")
        full_payload = res.json()
        self.assertIn("root", full_payload)

        res_cached = self.url_open(f"/web/webclient/load_menus?hash={current_hash}")
        self.assertEqual(res_cached.status_code, 304)
        self.assertFalse(
            res_cached.content,
            "304 response must have an empty body",
        )

        res_stale = self.url_open("/web/webclient/load_menus?hash=0deadbeef0")
        self.assertEqual(res_stale.status_code, 200)
        self.assertEqual(res_stale.headers.get("X-Menus-Hash"), current_hash)
        self.assertEqual(
            res_stale.json(),
            full_payload,
            "stale hash must return the full menus payload",
        )

    def test_preload_gate_reads_the_key_menu_storage_writes(self):
        self.authenticate("admin", "admin")
        page = self.url_open("/odoo").text

        gate = re.search(
            r'localStorage\.getItem\("webclient_menus_version"\)\s*===\s*([\w.]+)',
            page,
        )
        self.assertTrue(gate, "the preload's cache-validity check is gone")
        self.assertEqual(
            gate.group(1),
            "menus_cache_version",
            "the preload must compare against the server-composed key; "
            "recomposing it here is what drifted last time",
        )

        storage = tools.file_open(
            "web/static/src/webclient/menus/menu_storage.js",
        ).read()
        self.assertRegex(
            storage,
            r"function cacheVersion\(\) \{\s*return session\.menus_cache_version;",
            "menu_storage.js must read the same server-composed key",
        )

        session_info = json.loads(
            re.search(r"odoo\.__session_info__ = (\{.*?\});", page, re.DOTALL).group(1),
        )
        self.assertIn(
            "menus_cache_version",
            session_info,
            "session_info must carry the key both consumers read",
        )
