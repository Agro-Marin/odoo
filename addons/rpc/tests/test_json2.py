"""Tests for the /json/2 RPC controller."""

from odoo.tests import common
from odoo.tools import mute_logger


@common.tagged("post_install", "-at_install")
class TestJson2(common.HttpCase):
    """Routing, auth and argument validation of the JSON-2 endpoint."""

    def setUp(self):
        super().setUp()
        admin = self.env.ref("base.user_admin")
        self.api_key = (
            self.env["res.users.apikeys"]
            .with_user(admin)
            ._generate("rpc", "json2 test key", None)
        )
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

        self.enterContext(mute_logger("odoo.http"))

    def _rpc(self, model, method, payload):
        return self.url_open(
            f"/json/2/{model}/{method}", json=payload, headers=self.headers
        )

    def test_json2_root_hints_correct_usage(self):
        """The bare /json/2 route 404s with a usage hint."""
        response = self.url_open("/json/2")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Did you mean", response.text)

    def test_json2_rpc_returns_result(self):
        """An authenticated call returns the method's JSON result."""
        response = self._rpc("res.partner", "search_count", {"domain": []})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json(), 1)

    def test_json2_unknown_model_is_404(self):
        """Calling a model that does not exist yields 404, not a crash."""
        response = self._rpc("does.not.exist", "read", {})
        self.assertEqual(response.status_code, 404)

    def test_json2_model_method_with_ids_is_422(self):
        """@api.model methods reject explicit ids as unprocessable."""
        response = self._rpc(
            "res.partner", "create", {"ids": [1], "vals_list": [{"name": "X"}]}
        )
        self.assertEqual(response.status_code, 422)

    def test_json2_bad_signature_is_422(self):
        """Keyword arguments that do not bind to the signature yield 422."""
        response = self._rpc("res.partner", "search_count", {"bogus_kwarg": 1})
        self.assertEqual(response.status_code, 422)
