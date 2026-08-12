import hashlib
import hmac

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.base_credential_manager.tools import EndpointRateLimiter


class ApiChannelMixin(models.AbstractModel):
    """Shared fields and methods for inbound and outbound communication channels.

    Provides credentials (via base_credential_manager), rate limiting, retry
    config and auth-type selection to both api.endpoint.inbound and
    api.endpoint.outbound.
    """

    _name = "api.channel.mixin"
    _description = "Communication Channel Mixin"

    # ==================== Basic Information ====================

    name = fields.Char(
        required=True,
        translate=True,
        help="Human-readable name for this channel",
    )
    active = fields.Boolean(
        default=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        index=True,
        help="Company that owns this channel (for multi-tenancy isolation)",
    )
    sequence = fields.Integer(
        default=10,
    )
    code = fields.Char(
        index=True,
        help="Unique identifier code for programmatic access",
    )
    description = fields.Text(
        translate=True,
        help="Description of what this channel does",
    )

    # ==================== Credential Management ====================

    credential_id = fields.Many2one(
        comodel_name="credential.credential",
        ondelete="restrict",
        index=True,
        help="Encrypted credential for authentication. Managed by base_credential_manager.",
    )
    # Base selection holds only the auth types valid for every channel
    # (inbound, outbound, devices). Outbound-only methods (basic, oauth2) are
    # contributed by api.endpoint.outbound via selection_add.
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

    # ==================== Rate Limiting ====================

    rate_limit_enabled = fields.Boolean(
        string="Enable Rate Limiting",
        default=True,
        help="Enable rate limiting using token bucket algorithm",
    )
    rate_limit_requests = fields.Integer(
        string="Max Requests",
        default=100,
        help="Maximum number of requests allowed per time period",
    )
    rate_limit_period = fields.Selection(
        selection=[
            ("second", "Per Second"),
            ("minute", "Per Minute"),
            ("hour", "Per Hour"),
            ("day", "Per Day"),
        ],
        default="minute",
        help="Time period for rate limiting",
    )

    # ==================== Retry Configuration ====================

    retry_enabled = fields.Boolean(
        string="Enable Retry",
        default=True,
        help="Automatically retry failed operations with exponential backoff",
    )
    retry_max_attempts = fields.Integer(
        string="Max Retry Attempts",
        default=3,
        help="Maximum number of retry attempts before marking as failed",
    )
    retry_initial_delay = fields.Integer(
        string="Initial Retry Delay (seconds)",
        default=60,
        help="Initial delay before first retry. Increases exponentially.",
    )
    retry_backoff_type = fields.Selection(
        selection=[
            ("fixed", "Fixed Delay"),
            ("linear", "Linear Backoff"),
            ("exponential", "Exponential Backoff"),
        ],
        default="exponential",
        help="Strategy for increasing delay between retries",
    )

    # ==================== Statistics ====================

    date_last_activity = fields.Datetime(
        string="Last Activity",
        readonly=True,
        help="Timestamp of most recent activity (request received or sent)",
    )

    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains("rate_limit_requests")
    def _check_rate_limit_requests(self):
        """Validate rate limit requests is positive when enabled."""
        for record in self:
            if record.rate_limit_enabled and record.rate_limit_requests <= 0:
                raise ValidationError(
                    self.env._("Rate limit requests must be greater than 0"),
                )

    @api.constrains("retry_max_attempts")
    def _check_retry_max_attempts(self):
        """Validate retry attempts is positive when enabled."""
        for record in self:
            if record.retry_enabled and record.retry_max_attempts <= 0:
                raise ValidationError(
                    self.env._("Max retry attempts must be greater than 0"),
                )

    @api.constrains("retry_initial_delay")
    def _check_retry_initial_delay(self):
        """Validate retry delay is positive when enabled."""
        for record in self:
            if record.retry_enabled and record.retry_initial_delay <= 0:
                raise ValidationError(
                    self.env._("Initial retry delay must be greater than 0"),
                )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("credential_id", "credential_id.credential_value_encrypted")
    def _compute_credential_fingerprint(self):
        """Fingerprint the channel's secret so requests never have to decrypt it.

        Depends on the *encrypted* blob, so a rotation (which rewrites it)
        recomputes this exactly once per channel: the single decryption is paid
        at write time, never per request.
        """
        # ``credential.credential`` rate-limits decryption at 100 reads per user
        # per hour by default, and every anonymous inbound request runs as the
        # same public user. Reading ``credential_value`` on the request path
        # therefore throttled a correctly-authenticated device to 100 requests
        # per hour and reported the refusal as "invalid credentials" — while the
        # endpoint's own limit was deliberately set to 100 per *minute*. Storing
        # the digest moves that cost off the request path entirely.
        for record in self:
            value = record.credential_id.credential_value or ""
            record.credential_fingerprint = (
                hashlib.sha256(value.encode()).hexdigest() if value else False
            )

    # -------------------------------------------------------------------------
    # TOKEN VERIFICATION
    # -------------------------------------------------------------------------

    @api.model
    def _fingerprint_token(self, token):
        """Return the lookup digest for a presented shared secret.

        :param str token: the secret as presented by the caller.
        :return: hex SHA-256, or False for an empty token.
        :rtype: str | bool
        """
        # Deliberately unsalted: the digest has to be computable from the token
        # alone for the indexed reverse lookup in _find_by_credential_token to
        # work at all. That is sound here ONLY because these secrets are
        # high-entropy machine tokens (``secrets.token_hex(32)`` — 256 bits), so
        # there is no dictionary to run. Never point this at a user-chosen
        # password.
        return hashlib.sha256(token.encode()).hexdigest() if token else False

    def is_valid_token(self, token):
        """Return whether ``token`` is this channel's shared secret.

        Compares digests, so no decryption happens and no credential-manager
        decryption budget is spent.

        :param str token: the secret as presented by the caller.
        :rtype: bool
        """
        self.ensure_one()
        stored = self.sudo().credential_fingerprint
        if not stored or not token:
            return False
        return hmac.compare_digest(stored, self._fingerprint_token(token))

    @api.model
    def _find_by_credential_token(self, token, domain=None):
        """Return the channel(s) whose shared secret is ``token``.

        One indexed lookup on ``credential_fingerprint``; no decryption.

        :param str token: the secret as presented by the caller.
        :param domain: optional extra domain to pre-filter candidates.
        :return: matching recordset (normally one record, or empty).
        """
        fingerprint = self._fingerprint_token(token)
        if not fingerprint:
            return self.browse()
        return self.sudo().search(
            [("credential_fingerprint", "=", fingerprint), *(domain or [])]
        )

    # -------------------------------------------------------------------------
    # RATE LIMIT METHODS
    # -------------------------------------------------------------------------

    def check_rate_limit(self):
        """Return whether this channel is within its rate limit.

        Uses a DB-backed token-bucket limiter (accurate and multi-worker safe).

        :return: True if within the limit, False if exceeded
        :rtype: bool
        """
        self.ensure_one()

        if not self.rate_limit_enabled:
            return True

        limiter = EndpointRateLimiter(self.env, self)
        return limiter.check_limit()

    # -------------------------------------------------------------------------
    # RETRY METHODS
    # -------------------------------------------------------------------------

    def calculate_retry_delay(self, attempt_number):
        """Return the delay in seconds before the next retry attempt.

        :param attempt_number: current attempt number (1-based)
        :return: delay in seconds before the next retry
        :rtype: int
        """
        self.ensure_one()

        base_delay = self.retry_initial_delay

        if self.retry_backoff_type == "fixed":
            return base_delay
        if self.retry_backoff_type == "linear":
            return base_delay * attempt_number
        # exponential
        return base_delay * (2 ** (attempt_number - 1))

    def should_retry(self, attempt_number):
        """Return whether another retry attempt should be made.

        :param attempt_number: current attempt number (1-based)
        :return: True if a retry should happen, False if max attempts reached
        :rtype: bool
        """
        self.ensure_one()

        if not self.retry_enabled:
            return False

        return attempt_number < self.retry_max_attempts

    # -------------------------------------------------------------------------
    # ACTIVITY TRACKING
    # -------------------------------------------------------------------------

    def update_date_last_activity(self):
        """Update the last activity timestamp."""
        self.write({"date_last_activity": fields.Datetime.now()})
