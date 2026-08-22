from odoo.tests import HttpCase, tagged

_NAV_HEADERS = {
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}


@tagged("post_install", "-at_install", "web_http")
class TestJsonExportRoute(HttpCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("web.json.enabled", "1")
        self.env.ref("base.user_admin").group_ids |= self.env.ref(
            "base.group_allow_export"
        )
        self.authenticate("admin", "admin")

    def _json(self, query):
        return self.url_open(
            f"/json/1/action-base.action_partner_form?{query}",
            headers=_NAV_HEADERS,
        )

    def test_non_aggregatable_field_is_client_error_not_500(self):
        resp = self._json("groupby=type&fields=name")
        self.assertEqual(
            resp.status_code,
            400,
            f"expected 400 for a non-aggregatable measure, got {resp.status_code}: "
            f"{resp.text[:300]}",
        )
        self.assertIn("not aggregatable", resp.text)

    def test_grouped_count_still_works(self):
        resp = self._json("groupby=type")
        self.assertEqual(
            resp.status_code,
            200,
            f"grouped __count read should succeed, got {resp.status_code}: "
            f"{resp.text[:300]}",
        )
