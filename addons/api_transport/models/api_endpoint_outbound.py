import logging
import re
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ApiEndpointOutbound(models.Model):
    """Central registry for external API services.

    Extends api.channel.mixin with outbound-specific features: test/production
    endpoint URLs, OAuth 2.0, health monitoring, response caching,
    request/response logging and statistics.
    """

    _name = "api.endpoint.outbound"
    _inherit = [
        "api.channel.mixin",
        "mail.thread",
    ]
    _description = "Outbound Endpoint"
    _order = "sequence, name"
    _rec_name = "name"

    # ==================== Basic Information ====================

    category = fields.Selection(
        selection=[
            ("payment", "Payment Gateway"),
            ("delivery", "Delivery & Shipping"),
            ("communication", "Communication"),
            ("social", "Social Media"),
            ("tax", "Tax & EDI"),
            ("calendar", "Calendar & Scheduling"),
            ("cloud", "Cloud Storage"),
            ("ai", "Artificial Intelligence"),
            ("geocoding", "Geocoding & Maps"),
            ("analytics", "Analytics"),
            ("odoo_database", "Odoo Database"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
    )
    provider = fields.Char(
        help="Company providing the service",
    )
    website = fields.Char()
    documentation_url = fields.Char()
    environment = fields.Selection(
        selection=[
            ("test", "Test/Sandbox"),
            ("staging", "Staging"),
            ("production", "Production"),
        ],
        default="test",
        required=True,
        index=True,
    )

    # ==================== API Configuration ====================

    endpoint_url = fields.Char(
        required=True,
        help="Base URL for production environment",
    )
    endpoint_url_test = fields.Char(
        help="Base URL for test environment",
    )
    api_version = fields.Char()
    request_format = fields.Selection(
        selection=[
            ("json", "JSON"),
            ("form", "Form-encoded"),
            ("xml", "XML"),
            ("graphql", "GraphQL"),
        ],
        default="json",
    )
    # Outbound endpoints can additionally authenticate with methods that only
    # make sense when WE are the client: HTTP Basic auth and the OAuth2 client
    # flow. These are intentionally absent from the api.channel.mixin base
    # selection (which is shared with inbound endpoints and devices).
    auth_type = fields.Selection(
        selection_add=[
            ("basic", "Basic Authentication"),
            ("oauth2", "OAuth 2.0"),
        ],
        ondelete={"basic": "set default", "oauth2": "set default"},
    )

    # ==================== Odoo Database Configuration ====================

    is_odoo_database = fields.Boolean(
        compute="_compute_is_odoo_database",
        store=True,
    )
    odoo_database_name = fields.Char()
    odoo_hosting_type = fields.Selection(
        selection=[
            ("saas", "Odoo Online (SaaS)"),
            ("paas", "Odoo.sh (PaaS)"),
            ("onpremise", "On-Premise"),
            ("other", "Other"),
        ],
    )
    odoo_version = fields.Char(
        readonly=True,
    )
    odoo_protocol = fields.Selection(
        selection=[
            ("json2", "JSON/2 (Modern)"),
            ("xmlrpc", "XML-RPC (Legacy)"),
            ("auto", "Auto-detect"),
        ],
        default="auto",
    )

    # ==================== OAuth 2.0 Configuration ====================

    # Non-secret OAuth client configuration only. The client SECRET lives in
    # the linked credential.credential record (oauth_client_secret JSON
    # accessor) so every secret read goes through the vault's rate-limited,
    # audited decrypt path — see t23878.
    oauth_client_id = fields.Char()
    oauth_auth_endpoint = fields.Char()
    oauth_token_endpoint = fields.Char()
    oauth_scope = fields.Char(
        default="read write",
    )

    # ==================== Timeouts ====================

    timeout_connect = fields.Integer(
        default=10,
    )
    timeout_read = fields.Integer(
        default=30,
    )

    # ==================== Health Monitoring ====================

    health_check_enabled = fields.Boolean(
        default=True,
    )
    health_check_endpoint = fields.Char()
    health_check_interval = fields.Integer(
        default=15,
    )
    health_check_environment = fields.Selection(
        selection=[
            ("production", "Production"),
            ("staging", "Staging"),
            ("test", "Test/Sandbox"),
            ("any", "Any Active Credential"),
        ],
        default="production",
    )
    last_health_check = fields.Datetime(
        readonly=True,
    )
    is_healthy = fields.Boolean(
        default=True,
        readonly=True,
    )
    health_message = fields.Char(
        readonly=True,
    )

    # ==================== Response Caching ====================

    cache_enabled = fields.Boolean(
        default=False,
    )
    cache_ttl = fields.Integer(
        default=300,
    )
    cache_error_count = fields.Integer(
        default=0,
        readonly=True,
    )
    cache_last_error = fields.Datetime(
        readonly=True,
    )
    cache_health = fields.Selection(
        selection=[
            ("healthy", "Healthy"),
            ("degraded", "Degraded"),
            ("failed", "Failed"),
        ],
        compute="_compute_cache_health",
        store=True,
    )

    # ==================== Log Retention ====================

    log_retention_days = fields.Integer(
        default=90,
        help="Delete logs older than this. 0 = keep forever.",
    )
    allow_multiple_credentials = fields.Boolean(
        default=False,
        help="Allow multiple active credentials per company/environment. "
        "Useful for services like Telegram that support multiple bots.",
    )

    # ==================== Relationships ====================

    credential_ids = fields.One2many(
        comodel_name="credential.credential",
        inverse_name="service_id",
    )
    credential_count = fields.Integer(
        compute="_compute_credential_count",
        store=True,
    )
    event_log_ids = fields.One2many(
        comodel_name="api.event.log",
        compute="_compute_event_log_ids",
    )

    # ==================== Statistics ====================

    total_requests = fields.Integer(
        compute="_compute_statistics",
    )
    success_rate = fields.Float(
        compute="_compute_statistics",
    )
    avg_response_time = fields.Float(
        compute="_compute_statistics",
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "Service code must be unique!",
    )

    @api.constrains("code")
    def _check_code_format(self):
        """Validate service code format."""
        for service in self:
            if service.code and not re.match(r"^[a-z0-9_]+$", service.code):
                raise ValidationError(
                    self.env._(
                        "Code must contain only lowercase letters, numbers, and underscores"
                    ),
                )

    @api.constrains("is_odoo_database", "odoo_database_name")
    def _check_odoo_database_name(self):
        """Ensure database name is set for Odoo services."""
        for record in self:
            if record.is_odoo_database and not record.odoo_database_name:
                raise ValidationError(
                    self.env._("Database Name is required for Odoo Database services"),
                )

    @api.constrains("endpoint_url", "endpoint_url_test")
    def _check_endpoint_https(self):
        """Enforce HTTPS for production endpoints."""
        for record in self:
            if record.endpoint_url:
                if record.endpoint_url.startswith(
                    ("http://localhost", "http://127.0.0.1")
                ):
                    _logger.warning(
                        "Service '%s' uses localhost: %s",
                        record.name,
                        record.endpoint_url,
                    )
                elif not record.endpoint_url.startswith("https://"):
                    if not self.env.context.get("allow_http_production"):
                        raise ValidationError(
                            self.env._("Production endpoint must use HTTPS: %s")
                            % record.endpoint_url,
                        )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("category")
    def _compute_is_odoo_database(self):
        """Set flag based on category."""
        for service in self:
            service.is_odoo_database = service.category == "odoo_database"

    @api.depends("credential_ids", "credential_ids.active")
    def _compute_credential_count(self):
        """Count active credentials."""
        for service in self:
            service.credential_count = len(service.credential_ids.filtered("active"))

    def _compute_event_log_ids(self):
        """Get event logs for this service.

        One _read_group per compute instead of one search per record —
        avoids N+1 when the list view renders many services.
        """
        logs_by_ref: dict[str, list[int]] = {}
        if self.ids:
            channel_refs = [f"{record._name},{record.id}" for record in self]
            groups = self.env["api.event.log"]._read_group(
                domain=[
                    ("channel_id", "in", channel_refs),
                    ("direction", "=", "outbound"),
                ],
                groupby=["channel_id"],
                aggregates=["id:recordset"],
            )
            for ref, recordset in groups:
                logs_by_ref[ref] = recordset.ids
        for record in self:
            ref = f"{record._name},{record.id}"
            record.event_log_ids = [(6, 0, logs_by_ref.get(ref, []))]

    @api.depends("cache_error_count", "cache_last_error", "cache_enabled")
    def _compute_cache_health(self):
        """Compute cache health status."""
        for service in self:
            if not service.cache_enabled:
                service.cache_health = False
            elif service.cache_error_count == 0:
                service.cache_health = "healthy"
            elif service.cache_error_count < 10:
                service.cache_health = "degraded"
            else:
                service.cache_health = "failed"

    def _compute_statistics(self):
        """Compute request statistics for current month."""
        if not self.ids:
            for service in self:
                service.total_requests = 0
                service.success_rate = 0.0
                service.avg_response_time = 0.0
            return

        month_start = fields.Datetime.now().replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Build channel references for all services
        channel_refs = [f"api.endpoint.outbound,{sid}" for sid in self.ids]

        self.env.cr.execute(
            """
            SELECT
                channel_id,
                COUNT(*) as total_requests,
                COUNT(*) FILTER (WHERE status_code >= 200 AND status_code < 300) as successful,
                AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) as avg_duration
            FROM api_event_log
            WHERE channel_id = ANY(%s)
              AND direction = 'outbound'
              AND timestamp >= %s
            GROUP BY channel_id
            """,
            (channel_refs, month_start),
        )

        stats_by_channel = {
            row["channel_id"]: row for row in self.env.cr.dictfetchall()
        }

        for service in self:
            channel_ref = f"api.endpoint.outbound,{service.id}"
            stats = stats_by_channel.get(channel_ref)

            if stats:
                total = stats["total_requests"] or 0
                successful = stats["successful"] or 0
                service.total_requests = total
                service.success_rate = (successful / total * 100) if total > 0 else 0.0
                service.avg_response_time = stats["avg_duration"] or 0.0
            else:
                service.total_requests = 0
                service.success_rate = 0.0
                service.avg_response_time = 0.0

    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------

    def action_test_connection(self) -> dict[str, Any]:
        """Test connection to the external service with a live request."""
        self.ensure_one()
        credential = self.credential_ids.filtered("active")[:1]
        if not credential:
            raise ValidationError(self.env._("No active credentials configured"))

        endpoint = self.health_check_endpoint or "/"
        try:
            client = self._get_api_client(credential)
            response = client.get(endpoint)
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Connection failed"),
                    "message": str(e)[:255],
                    "type": "danger",
                    "sticky": False,
                },
            }

        status_code = response.get("status_code", 0)
        ok = 200 <= status_code < 300
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Connection OK") if ok else self.env._("Warning"),
                "message": self.env._("Service responded with HTTP %s", status_code),
                "type": "success" if ok else "warning",
                "sticky": False,
            },
        }

    def action_view_credentials(self) -> dict[str, Any]:
        """Open credentials view."""
        self.ensure_one()
        return {
            "name": self.env._("Credentials"),
            "type": "ir.actions.act_window",
            "res_model": "credential.credential",
            "view_mode": "list,form",
            "domain": [("service_id", "=", self.id)],
            "context": {"default_service_id": self.id},
        }

    def action_view_logs(self) -> dict[str, Any]:
        """Open request logs view."""
        self.ensure_one()
        channel_ref = f"{self._name},{self.id}"
        return {
            "name": self.env._("Request Logs"),
            "type": "ir.actions.act_window",
            "res_model": "api.event.log",
            "view_mode": "list,form",
            "domain": [
                ("channel_id", "=", channel_ref),
                ("direction", "=", "outbound"),
            ],
        }

    def action_check_health(self) -> dict[str, Any]:
        """Run an on-demand health check for the selected services.

        Public wrapper around ``_perform_health_check``. Iterates over
        every record in ``self`` and persists ``last_health_check`` /
        ``is_healthy`` / ``health_message``. Submodules override
        ``_perform_health_check`` to make a real HTTP call (api_gateway
        does this via ``get_api_client``).
        """
        for record in self:
            try:
                record._perform_health_check()
            except Exception as e:
                # Capture and persist the failure rather than letting it
                # bubble up — the caller (button or test) wants the row
                # state updated, not a traceback.
                _logger.exception("Health check failed for service %s", record.code)
                record.write(
                    {
                        "last_health_check": fields.Datetime.now(),
                        "is_healthy": False,
                        "health_message": str(e)[:255],
                    },
                )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Health Check"),
                "message": self.env._(
                    "Health check completed for %s service(s).", len(self)
                ),
                "type": "info",
            },
        }

    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------

    @api.model
    def cron_reset_cache_errors(self):
        """Reset cache error counters daily."""
        services = self.search([("cache_error_count", ">", 0)])
        if services:
            services.write(
                {
                    "cache_error_count": 0,
                    "cache_last_error": False,
                },
            )
            _logger.info("Reset cache errors for %d services", len(services))

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    @api.model
    def cron_health_check_all(self):
        """Scheduled health check for all active services."""
        services = self.search(
            [
                ("active", "=", True),
                ("health_check_enabled", "=", True),
            ],
        )

        for service in services:
            try:
                service._perform_health_check()
            except Exception as e:
                _logger.error("Health check failed for %s: %s", service.code, e)

    def _perform_health_check(self):
        """Perform health check on this service."""
        self.ensure_one()
        if self.health_check_environment == "any":
            credential = self.credential_ids.filtered("active").sorted(
                key=lambda c: (c.environment != "production", c.sequence),
            )[:1]
        else:
            credential = self.credential_ids.filtered(
                lambda c: c.active and c.environment == self.health_check_environment,
            )[:1]

        if not credential:
            env_label = (
                "active"
                if self.health_check_environment == "any"
                else self.health_check_environment
            )
            self.write(
                {
                    "last_health_check": fields.Datetime.now(),
                    "is_healthy": False,
                    "health_message": f"No {env_label} credentials",
                },
            )
            return

        # Issue a real request against the service and record the outcome. The
        # client comes from _get_api_client so downstream transports (e.g.
        # api_gateway's Odoo-database client) are honoured. The probe is logged
        # to api.event.log like any other outbound call.
        endpoint = self.health_check_endpoint or "/"
        try:
            client = self._get_api_client(credential)
            response = client.get(endpoint)
        except Exception as e:
            _logger.warning("Health check call failed for %s: %s", self.code, e)
            self.write(
                {
                    "last_health_check": fields.Datetime.now(),
                    "is_healthy": False,
                    "health_message": str(e)[:255],
                },
            )
            return

        status_code = response.get("status_code", 0)
        is_ok = 200 <= status_code < 300
        self.write(
            {
                "last_health_check": fields.Datetime.now(),
                "is_healthy": is_ok,
                "health_message": (
                    f"HTTP {status_code}"
                    if is_ok
                    else f"Unexpected status {status_code}"
                ),
            },
        )

    def _get_api_client(self, credential=None):
        """Return an HTTP client for this service.

        Hook for downstream modules that add non-HTTP transports: the base
        returns the generic ``APIGatewayClient`` via the transport factory;
        ``api_gateway`` overrides this to dispatch ``is_odoo_database`` services
        to its Odoo-to-Odoo client.
        """
        self.ensure_one()
        # Local import: tools imports the models package at load time, so a
        # top-level import here would be circular.
        from odoo.addons.api_transport.tools import (  # pylint: disable=import-outside-toplevel
            get_api_client,
        )

        return get_api_client(
            self.env,
            self.code,
            company_id=(credential.company_id.id if credential else None) or None,
            credential_id=credential.id if credential else None,
        )
