from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.credential.tools import EndpointRateLimiter


class ApiChannelMixin(models.AbstractModel):
    _name = "api.channel.mixin"
    _inherit = ["credential.auth.mixin"]
    _description = "Communication Channel Mixin"

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
    rate_limit_strict = fields.Boolean(
        string="Strict Rate Limiting",
        default=False,
        help="Deny the request when the rate-limit bucket cannot be read "
        "(lock contention, timeout, internal error) instead of allowing it. "
        "Enable wherever the limit is a security control rather than a "
        "best-effort cap.",
    )

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

    date_last_activity = fields.Datetime(
        string="Last Activity",
        readonly=True,
        help="Timestamp of most recent activity (request received or sent)",
    )

    @api.constrains("rate_limit_requests")
    def _check_rate_limit_requests(self):
        for record in self:
            if record.rate_limit_enabled and record.rate_limit_requests <= 0:
                raise ValidationError(
                    self.env._("Rate limit requests must be greater than 0"),
                )

    @api.constrains("retry_max_attempts")
    def _check_retry_max_attempts(self):
        for record in self:
            if record.retry_enabled and record.retry_max_attempts <= 0:
                raise ValidationError(
                    self.env._("Max retry attempts must be greater than 0"),
                )

    @api.constrains("retry_initial_delay")
    def _check_retry_initial_delay(self):
        for record in self:
            if record.retry_enabled and record.retry_initial_delay <= 0:
                raise ValidationError(
                    self.env._("Initial retry delay must be greater than 0"),
                )

    def check_rate_limit(self, company_id=None):
        self.ensure_one()

        if not self.rate_limit_enabled:
            return True

        limiter = EndpointRateLimiter(self.env, self, company_id)
        return limiter.check_limit()

    def calculate_retry_delay(self, attempt_number):
        self.ensure_one()

        base_delay = self.retry_initial_delay

        if self.retry_backoff_type == "fixed":
            return base_delay
        if self.retry_backoff_type == "linear":
            return base_delay * attempt_number
        return base_delay * (2 ** (attempt_number - 1))

    def should_retry(self, attempt_number):
        self.ensure_one()

        if not self.retry_enabled:
            return False

        return attempt_number < self.retry_max_attempts

    def update_date_last_activity(self):
        self.write({"date_last_activity": fields.Datetime.now()})
