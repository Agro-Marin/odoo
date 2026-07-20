from odoo import api, fields, models


class CredentialCategory(models.Model):
    """Credential category defining the type of credentials (API key, bearer token, OAuth 2.0, certificate, etc.)."""

    _name = "credential.category"
    _description = "Credential Category"
    _order = "sequence, name"

    name = fields.Char(
        string="Category Name",
        required=True,
        translate=True,
        help="Display name for this credential category",
    )
    code = fields.Char(
        string="Technical Code",
        required=True,
        index=True,
        help="Technical identifier (e.g., 'api_key', 'certificate'). Used for programmatic access.",
    )
    description = fields.Text(
        translate=True,
        help="Detailed description of this credential type",
    )
    sequence = fields.Integer(
        default=10,
        help="Display order in lists",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive categories cannot be used for new credentials",
    )
    storage_hint = fields.Selection(
        selection=[
            ("simple", "Simple Value"),
            ("json", "JSON Data"),
            ("certificate", "Certificate/Key"),
        ],
        string="Storage Type",
        default="simple",
        required=True,
        help="Recommended storage method for credentials of this type:\n"
        "• Simple Value: Single string (API keys, tokens)\n"
        "• JSON Data: Multiple key-value pairs (OAuth2, Basic Auth)\n"
        "• Certificate/Key: Binary certificate and key data",
    )
    icon = fields.Char(
        default="fa-key",
        help="FontAwesome icon class for UI display",
    )

    # ==================== Default Settings for Credentials ====================
    # These defaults are applied to new credentials of this category
    # but can be overridden at the credential level.

    default_enable_rate_limiting = fields.Boolean(
        string="Enable Rate Limiting (Default)",
        default=True,
        help="Default rate limiting setting for credentials of this category. Can be overridden per credential.",
    )
    default_rate_limit_max_attempts = fields.Integer(
        string="Rate Limit (Default)",
        default=100,
        help="Default maximum decryption attempts per hour. Can be overridden per credential.",
    )
    default_auto_validate_health = fields.Boolean(
        string="Auto Health Check (Default)",
        default=False,
        help="Default setting for automatic health validation. Can be overridden per credential.",
    )
    default_allow_key_fallback = fields.Boolean(
        string="Allow Key Fallback (Default)",
        default=True,
        help="Default setting for allowing decryption with old key versions. Can be overridden per credential.",
    )

    credential_ids = fields.One2many(
        comodel_name="credential.credential",
        inverse_name="category_id",
        string="Credentials",
        help="Credentials of this category",
    )
    credential_count = fields.Integer(
        compute="_compute_credential_count",
        store=False,
    )

    # Unique constraint on code
    _code_uniq = models.Constraint(
        "unique(code)",
        "Category code must be unique!",
    )

    @api.depends("name", "code")
    def _compute_display_name(self):
        """Compute display name showing name and code."""
        for category in self:
            category.display_name = f"{category.name} ({category.code})"

    @api.depends("credential_ids")
    def _compute_credential_count(self):
        """Compute the number of credentials in this category.

        Uses a single grouped aggregate instead of ``len(credential_ids)`` so
        we don't prefetch and materialize every related credential record just
        to count them — cheaper and it respects record rules on the count.
        """
        counts = dict(
            self.env["credential.credential"]._read_group(
                [("category_id", "in", self.ids)],
                groupby=["category_id"],
                aggregates=["__count"],
            )
        )
        for category in self:
            category.credential_count = counts.get(category, 0)
