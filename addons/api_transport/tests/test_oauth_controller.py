from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.api_transport.controllers.oauth import OAuthController


class TestOAuthTokenExchange(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["api.endpoint.outbound"].create(
            {
                "name": "OAuth Test Service",
                "code": "oauth_exchange_test",
                "endpoint_url": "https://api.oauth.test",
                "auth_type": "oauth2",
                "oauth_client_id": "app-client-id",
                "oauth_auth_endpoint": "https://oauth.test/authorize",
                "oauth_token_endpoint": "https://oauth.test/token",
            }
        )
        cls.category_oauth2 = cls.env.ref("credential.credential_category_oauth2")
        cls.controller = OAuthController()

    def _make_credential(self, **extra):
        values = {
            "name": "OAuth Exchange Credential",
            "category_id": self.category_oauth2.id,
            "endpoint_id": self.service.id,
            "company_id": self.env.company.id,
        }
        values.update(extra)
        return self.env["credential.credential"].create(values)

    def _exchange(self, credential):
        response = MagicMock()
        response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        response.raise_for_status.return_value = None
        with (
            patch.object(
                OAuthController,
                "_build_redirect_uri",
                return_value="https://odoo.test/api_gateway/oauth/callback",
            ),
            patch(
                "odoo.addons.api_transport.controllers.oauth.requests.post",
                return_value=response,
            ) as mock_post,
        ):
            tokens = self.controller._exchange_code_for_tokens(credential, "auth-code")
        return tokens, mock_post

    def test_exchange_sends_secret_from_credential(self):
        credential = self._make_credential(oauth_client_secret="vault-s3cr3t")

        tokens, mock_post = self._exchange(credential)

        self.assertEqual(tokens["access_token"], "new-access-token")
        sent = mock_post.call_args.kwargs["data"]
        self.assertEqual(sent["client_secret"], "vault-s3cr3t")
        self.assertEqual(sent["client_id"], "app-client-id")
        self.assertEqual(sent["grant_type"], "authorization_code")

    def test_exchange_public_client_omits_secret(self):
        credential = self._make_credential(oauth_access_token="existing-token")

        _tokens, mock_post = self._exchange(credential)

        self.assertNotIn("client_secret", mock_post.call_args.kwargs["data"])
