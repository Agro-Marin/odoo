import hashlib
import hmac

from odoo import api, fields, models


class CredentialAuthMixin(models.AbstractModel):
    _name = "credential.auth.mixin"
    _description = "Credential Authentication Mixin"

    credential_id = fields.Many2one(
        comodel_name="credential.credential",
        string="Active Credential",
        ondelete="restrict",
        index=True,
        help="Encrypted credential for authentication. Managed by credential.",
    )
    auth_type = fields.Selection(
        selection=[
            ("none", "No Authentication"),
            ("bearer", "Bearer Token"),
            ("api_key", "API Key"),
            ("hmac_sha256", "HMAC-SHA256"),
            ("hmac_sha512", "HMAC-SHA512"),
            ("custom", "Custom"),
        ],
        string="Authentication Type",
        default="bearer",
        required=True,
        help="Method used for authentication",
    )
    credential_fingerprint = fields.Char(
        compute="_compute_credential_fingerprint",
        store=True,
        index=True,
        compute_sudo=True,
        copy=False,
        groups="base.group_system",
        help="SHA-256 of the credential's secret. Lets a presented token be "
        "verified, and its channel found, without decrypting anything.",
    )

    @api.depends("credential_id", "credential_id.credential_value_encrypted")
    def _compute_credential_fingerprint(self):
        for record in self:
            credential = record.credential_id
            value = (
                credential._get_secret(prefer=record._secret_slot_for_auth_type())
                if credential
                else False
            )
            record.credential_fingerprint = (
                hashlib.sha256(value.encode()).hexdigest() if value else False
            )

    def _secret_slot_for_auth_type(self):
        self.ensure_one()
        return {
            "bearer": "bearer_token",
            "api_key": "api_key",
        }.get(self.auth_type)

    @api.model
    def _fingerprint_token(self, token):
        return hashlib.sha256(token.encode()).hexdigest() if token else False

    def is_valid_token(self, token):
        self.ensure_one()
        stored = self.sudo().credential_fingerprint
        if not stored or not token:
            return False
        return hmac.compare_digest(stored, self._fingerprint_token(token))

    @api.model
    def _find_by_credential_token(self, token, domain=None):
        fingerprint = self._fingerprint_token(token)
        if not fingerprint:
            return self.browse()
        return self.sudo().search(
            [("credential_fingerprint", "=", fingerprint), *(domain or [])]
        )
