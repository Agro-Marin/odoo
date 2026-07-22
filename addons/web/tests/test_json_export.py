from odoo.tests import HttpCase, tagged

# Browser Sec-Fetch-* headers: the /json/1 route is auth="bearer", which accepts
# a logged-in session only for an interactive navigation (see
# base.ir_http._auth_method_bearer -> check_sec_headers).
_NAV_HEADERS = {
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}


@tagged("post_install", "-at_install", "web_unit")
class TestJsonExportRoute(HttpCase):
    """Regression coverage for the /json export controller (controllers/json.py)."""

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("web.json.enabled", "1")
        # /json requires export permission.
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
        """A char field passed as a grouped measure must 400, never 500.

        ``fields=name`` (aggregator is None) used to expand to the aggregate
        token ``"name:None"`` and reach ``web_read_group``, which raises a raw
        ``ValueError`` -> HTTP 500. The controller now rejects it up front like
        the sibling limit/offset/domain client-error paths.
        """
        resp = self._json("groupby=type&fields=name")
        self.assertEqual(
            resp.status_code,
            400,
            f"expected 400 for a non-aggregatable measure, got {resp.status_code}: "
            f"{resp.text[:300]}",
        )
        self.assertIn("not aggregatable", resp.text)

    def test_grouped_count_still_works(self):
        """Control: the same route without a bad measure resolves (no 500).

        Proves the 400 above is the guard firing, not a broken test fixture.
        """
        resp = self._json("groupby=type")
        self.assertEqual(
            resp.status_code,
            200,
            f"grouped __count read should succeed, got {resp.status_code}: "
            f"{resp.text[:300]}",
        )
