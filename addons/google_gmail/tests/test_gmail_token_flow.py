"""Tests for the Gmail OAuth token flows, with the HTTP layer mocked."""

import time
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MIXIN_MODULE = "odoo.addons.google_gmail.models.google_gmail_mixin"


@tagged("post_install", "-at_install")
class TestGmailTokenFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixin = cls.env["google.gmail.mixin"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "google_gmail_client_id", "test-client-id"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "google_gmail_client_secret", "test-client-secret"
        )

    def _response(self, ok=True, payload=None):
        response = MagicMock()
        response.ok = ok
        response.json.return_value = payload or {}
        response.text = "mock"
        return response

    def test_fetch_token_returns_payload(self):
        """A successful token request returns the endpoint's JSON payload."""
        payload = {"access_token": "AT", "expires_in": 3600}
        with patch(
            f"{MIXIN_MODULE}.requests.post",
            return_value=self._response(payload=payload),
        ) as post:
            result = self.Mixin._fetch_gmail_token("refresh_token", refresh_token="RT")
        self.assertEqual(result, payload)
        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["client_id"], "test-client-id")
        self.assertEqual(sent["grant_type"], "refresh_token")

    def test_fetch_token_http_error_rejected(self):
        """A non-2xx token response surfaces as a UserError (negative)."""
        with (
            patch(
                f"{MIXIN_MODULE}.requests.post", return_value=self._response(ok=False)
            ),
            self.assertRaises(UserError),
        ):
            self.Mixin._fetch_gmail_token("refresh_token", refresh_token="RT")

    def test_refresh_token_maps_tuple_and_expiration(self):
        """The authorization-code exchange maps to (refresh, access, expiry)."""
        payload = {"refresh_token": "RT", "access_token": "AT", "expires_in": 1000}
        before = int(time.time())
        with patch(
            f"{MIXIN_MODULE}.requests.post",
            return_value=self._response(payload=payload),
        ):
            refresh, access, expiration = self.Mixin._fetch_gmail_refresh_token("CODE")
        self.assertEqual((refresh, access), ("RT", "AT"))
        self.assertGreaterEqual(expiration, before + 1000)

    def test_access_token_uses_credentials_when_configured(self):
        """With client credentials set, the direct Google endpoint is used."""
        payload = {"access_token": "AT2", "expires_in": 500}
        with patch(
            f"{MIXIN_MODULE}.requests.post",
            return_value=self._response(payload=payload),
        ) as post:
            access, _expiration = self.Mixin._fetch_gmail_access_token("RT")
        self.assertEqual(access, "AT2")
        post.assert_called_once()

    def test_iap_http_error_rejected(self):
        """An IAP transport failure surfaces as a UserError (negative)."""
        with (
            patch(
                f"{MIXIN_MODULE}.requests.get", return_value=self._response(ok=False)
            ),
            self.assertRaises(UserError),
        ):
            self.Mixin._fetch_gmail_access_token_iap("RT")

    def test_iap_payload_error_rejected(self):
        """An IAP error payload is converted into a UserError (negative)."""
        with (
            patch(
                f"{MIXIN_MODULE}.requests.get",
                return_value=self._response(payload={"error": "no_subscription"}),
            ),
            self.assertRaises(UserError),
        ):
            self.Mixin._fetch_gmail_access_token_iap("RT")
