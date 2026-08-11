import json
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CredentialCredential(models.Model):
    """Extend credential.credential to support outbound endpoint linking.

    The auth-header construction lives here rather than in
    ``base_credential_manager`` because it reads the *service*'s ``auth_type``,
    ``code`` and ``api_version``, and ``service_id`` is declared in this module.
    The vault knows nothing about ``api.endpoint.outbound`` — it depends on
    ``base`` alone — so this could not sit any lower without inverting the
    dependency.
    """

    _name = "credential.credential"
    _inherit = ["credential.credential", "mail.thread"]

    service_id = fields.Many2one(
        comodel_name="api.endpoint.outbound",
        string="Outbound Endpoint",
        index=True,
        ondelete="cascade",
        help="The outbound API endpoint this credential is associated with.",
    )
    custom_headers = fields.Text(
        groups="base.group_system",
        help="Additional HTTP headers in JSON format: {'X-Custom-Header': 'value'}",
    )

    @api.constrains("custom_headers")
    def _check_custom_headers_json(self):
        """Reject custom_headers that is not a JSON object.

        Caught here rather than at request time: a malformed value would
        otherwise be discovered mid-call, logged, and silently dropped, leaving
        an integration mysteriously missing a header it was configured with.
        """
        for credential in self:
            if not credential.custom_headers:
                continue
            try:
                parsed = json.loads(credential.custom_headers)
            except (json.JSONDecodeError, ValueError, TypeError) as err:
                raise ValidationError(
                    self.env._(
                        "Custom headers must be valid JSON: %(error)s", error=err
                    )
                ) from err
            if not isinstance(parsed, dict):
                raise ValidationError(
                    self.env._("Custom headers must be a JSON object of header names to values.")
                )

    def get_auth_headers(self):
        """Build the authentication headers this credential's service expects.

        :return: headers to merge into an outbound request
        :rtype: dict
        """
        self.ensure_one()
        headers = {}

        if not self.service_id:
            return headers

        auth_type = self.service_id.auth_type
        service_code = self.service_id.code
        api_version = self.service_id.api_version

        if auth_type == "bearer" and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif auth_type == "api_key" and self.api_key:
            # Provider-specific key headers. Several providers do NOT accept
            # the generic ``Authorization: Bearer`` + ``X-API-Key`` pair:
            #   - Anthropic (Claude) expects ``x-api-key`` plus the
            #     ``anthropic-version`` header.
            #   - Google Generative Language API (Gemini) expects
            #     ``x-goog-api-key``.
            if service_code == "claude":
                headers["x-api-key"] = self.api_key
                if api_version:
                    headers["anthropic-version"] = api_version
            elif service_code == "gemini":
                headers["x-goog-api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["X-API-Key"] = self.api_key
        elif auth_type == "oauth2" and self.oauth_access_token:
            headers["Authorization"] = f"Bearer {self.oauth_access_token}"

        if self.custom_headers:
            try:
                headers.update(json.loads(self.custom_headers))
            except (json.JSONDecodeError, ValueError, TypeError):
                # Constrained on write, so this only fires for rows written
                # before that constraint existed.
                _logger.warning(
                    "Invalid custom_headers JSON for credential %s: %s",
                    self.id,
                    self.custom_headers[:100] if self.custom_headers else "",
                )

        return headers
