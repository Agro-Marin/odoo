from odoo import Command, api
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

        # Patch search to only return these menus
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
                "actionID": self.action.id,  # Take the first action in children (see load_web_menus)
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
        """Matching ``?hash=`` → empty 304; stale hash → full payload."""
        res = self.url_open("/web/webclient/load_menus")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")
        current_hash = res.headers.get("X-Menus-Hash")
        self.assertTrue(current_hash, "200 response must expose X-Menus-Hash")
        full_payload = res.json()
        self.assertIn("root", full_payload)

        # Matching hash → 304-equivalent, no payload re-download
        res_cached = self.url_open(f"/web/webclient/load_menus?hash={current_hash}")
        self.assertEqual(res_cached.status_code, 304)
        self.assertFalse(
            res_cached.content,
            "304 response must have an empty body",
        )

        # Stale hash → full payload again, with the current hash
        res_stale = self.url_open("/web/webclient/load_menus?hash=0deadbeef0")
        self.assertEqual(res_stale.status_code, 200)
        self.assertEqual(res_stale.headers.get("X-Menus-Hash"), current_hash)
        self.assertEqual(
            res_stale.json(),
            full_payload,
            "stale hash must return the full menus payload",
        )
