import hashlib
import json
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ApiEventLog(models.Model):
    """Unified event log for all API communications.

    Stores events from both inbound (webhooks, IoT) and outbound (API calls)
    communications. Provides processing state tracking, retry logic, and audit trail.

    The 'direction' field distinguishes between:
    - inbound: Events received from external systems (webhooks, IoT devices)
    - outbound: Requests sent to external APIs
    """

    _name = "api.event.log"
    _description = "Communication Event Log"
    _inherit = ["mail.thread"]
    _order = "timestamp desc, id desc"
    _rec_name = "display_name"

    # ==================== Core Fields ====================

    direction = fields.Selection(
        selection=[
            ("inbound", "Inbound"),
            ("outbound", "Outbound"),
        ],
        required=True,
        index=True,
        help="Direction of communication: inbound (receiving) or outbound (sending)",
    )
    channel_id = fields.Reference(
        selection="_selection_channel_models",
        required=True,
        index=True,
        help="Reference to the channel (endpoint or service) for this event",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        index=True,
        help="Company that owns this log entry. Defaults to the channel "
        "(endpoint) company, but the caller can override at create time "
        "with the effective request company (e.g. the credential's "
        "company in multi-tenant outbound calls).",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        index=True,
        help="User who initiated the request (outbound) or processed the event (inbound)",
    )
    credential_id = fields.Many2one(
        comodel_name="credential.credential",
        ondelete="set null",
        index=True,
        help="Credential used for this communication",
    )
    display_name = fields.Char(
        compute="_compute_display_name",
        store=True,
    )
    channel_name = fields.Char(
        compute="_compute_channel_name",
        store=True,
        index=True,
        help="Cached channel name for faster searches",
    )

    # ==================== Timing ====================

    timestamp = fields.Datetime(
        default=fields.Datetime.now,
        required=True,
        index=True,
        help="When the event was received (inbound) or request was initiated (outbound)",
    )
    date_completed = fields.Datetime(
        readonly=True,
        help="Timestamp when processing completed",
    )
    duration_ms = fields.Float(
        digits=(10, 2),
        help="Processing time in milliseconds",
    )
    performance_rating = fields.Selection(
        selection=[
            ("excellent", "Excellent (< 100ms)"),
            ("good", "Good (100-500ms)"),
            ("average", "Average (500-1000ms)"),
            ("slow", "Slow (1-3s)"),
            ("very_slow", "Very Slow (> 3s)"),
        ],
        compute="_compute_performance_rating",
        store=True,
    )

    # ==================== Request/Payload Data ====================

    # For inbound: the received payload
    # For outbound: the request body
    request_payload = fields.Text(
        help="Request body (inbound: received payload, outbound: sent body)",
    )
    request_payload_hash = fields.Char(
        compute="_compute_payload_hash",
        store=True,
        index=True,
        help="SHA256 hash for duplicate detection",
    )
    request_payload_size = fields.Integer(
        compute="_compute_payload_sizes",
        store=True,
    )

    # For outbound only
    request_method = fields.Selection(
        selection=[
            ("GET", "GET"),
            ("POST", "POST"),
            ("PUT", "PUT"),
            ("PATCH", "PATCH"),
            ("DELETE", "DELETE"),
            ("HEAD", "HEAD"),
            ("OPTIONS", "OPTIONS"),
        ],
        index=True,
    )
    request_url = fields.Char(
        index=True,
    )
    request_endpoint = fields.Char(
        compute="_compute_request_endpoint",
        store=True,
        index=True,
    )
    request_headers = fields.Json()

    # ==================== Response Data ====================

    response_payload = fields.Text(
        help="Response body (inbound: our response, outbound: received response)",
    )
    response_payload_size = fields.Integer(
        compute="_compute_payload_sizes",
        store=True,
    )
    response_headers = fields.Json()

    # For outbound only
    status_code = fields.Integer(
        index=True,
    )
    status_category = fields.Selection(
        selection=[
            ("success", "2xx Success"),
            ("redirect", "3xx Redirect"),
            ("client_error", "4xx Client Error"),
            ("server_error", "5xx Server Error"),
            ("unknown", "Unknown"),
        ],
        compute="_compute_status_category",
        store=True,
        index=True,
    )

    # For inbound only
    source_ip = fields.Char(
        index=True,
        help="IP address of the client that sent the event",
    )

    # ==================== Webhook/Inbound Event Fields ====================

    event_type = fields.Char(
        index=True,
        help="Type of event (e.g., 'payment.success', 'push'). Used for inbound webhooks.",
    )
    event_id_external = fields.Char(
        index=True,
        help="Unique event ID from external service for deduplication",
    )
    signature_verified = fields.Boolean(
        default=False,
        help="Whether the inbound request signature was successfully verified",
    )
    user_agent = fields.Char(
        help="HTTP User-Agent header from the inbound request",
    )
    processing_result = fields.Text(
        help="Return value or result from handler execution",
    )
    stack_trace = fields.Text(
        help="Full stack trace for debugging failed events",
    )

    # ==================== Processing State ====================

    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("duplicate", "Duplicate"),
            ("retry", "Retry Scheduled"),
        ],
        required=True,
        default="pending",
        index=True,
        tracking=True,
        help="Current processing state",
    )
    is_success = fields.Boolean(
        compute="_compute_is_success",
        store=True,
        index=True,
    )

    # ==================== Error Handling ====================

    error_message = fields.Text(
        readonly=True,
    )
    error_type = fields.Selection(
        selection=[
            ("network", "Network Error"),
            ("timeout", "Timeout"),
            ("auth", "Authentication Error"),
            ("validation", "Validation Error"),
            ("rate_limit", "Rate Limit Exceeded"),
            ("server", "Server Error"),
            ("duplicate", "Duplicate Event"),
            ("other", "Other"),
        ],
    )

    # ==================== Retry ====================

    retry_count = fields.Integer(
        default=0,
        readonly=True,
    )
    date_next_retry = fields.Datetime(
        readonly=True,
        index=True,
    )

    # ==================== Caching (Outbound) ====================

    cache_hit = fields.Boolean(
        default=False,
        index=True,
    )
    cache_key = fields.Char(
        index=True,
    )

    # ==================== Tracing ====================

    trace_id = fields.Char(
        index=True,
        help="Unique ID for correlating related events",
    )
    origin_model = fields.Char(
        help="Odoo model that triggered this communication",
    )
    origin_record_id = fields.Integer()
    tags = fields.Char(
        help="Comma-separated tags for categorization",
    )

    # ==================== Indexes & Constraints ====================

    # Composite index for duplicate detection (inbound)
    _duplicate_detection_idx = models.Index(
        "(channel_id, request_payload_hash, timestamp)",
    )

    # Index for retry queue queries
    _retry_queue_idx = models.Index(
        "(state, date_next_retry)",
    )

    # Index for rate limiting lookups
    _rate_limit_idx = models.Index(
        "(channel_id, timestamp, company_id)",
    )

    # Unique constraint for external ID deduplication (inbound webhooks)
    # Prevents processing the same external event twice per channel
    _event_external_unique = models.UniqueIndex(
        "(channel_id, event_id_external) WHERE event_id_external IS NOT NULL",
        "External event ID must be unique per channel!",
    )

    # -------------------------------------------------------------------------
    # SELECTION METHODS
    # -------------------------------------------------------------------------

    @api.model
    def _selection_channel_models(self):
        """Return the (model_name, display_name) list of channel models.

        :return: (model_name, display_name) tuples
        :rtype: list
        """
        # Walk the full inheritance tree rooted at api.channel.mixin to find all
        # concrete models (incl. grandchildren like remote.device); a BFS is
        # needed because _inherit_children tracks only direct parents.
        mixin_cls = self.env.registry.get("api.channel.mixin")
        if not mixin_cls:
            return [("api.endpoint.outbound", "Outbound Service")]

        channels = []
        visited = set()
        queue = list(mixin_cls._inherit_children)

        while queue:
            child_name = queue.pop(0)
            if child_name in visited or child_name == "api.channel.mixin":
                continue
            visited.add(child_name)

            child_cls = self.env.registry.get(child_name)
            if not child_cls:
                continue

            # Enqueue grandchildren for traversal
            queue.extend(child_cls._inherit_children)

            if not getattr(child_cls, "_abstract", False):
                label = getattr(child_cls, "_description", child_name)
                channels.append((child_name, label))

        return channels or [("api.endpoint.outbound", "Outbound Service")]

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("channel_id")
    def _compute_company_id(self):
        """Default ``company_id`` to the channel's company.

        The field is ``readonly=False`` so callers (api_gateway's
        outbound client, inbound webhook handlers) can pass an explicit
        ``company_id`` reflecting the EFFECTIVE request tenant — for
        outbound calls that's the credential's ``company_id``, not the
        endpoint owner's.  Only fall back to the channel's company when
        the caller did not provide one.
        """
        for record in self:
            if record.company_id:
                # Honour caller-provided value (e.g. from the credential).
                continue
            if record.channel_id and hasattr(record.channel_id, "company_id"):
                record.company_id = record.channel_id.company_id
            else:
                record.company_id = False

    @api.depends("channel_id")
    def _compute_channel_name(self):
        """Cache channel name for faster searches."""
        for record in self:
            if record.channel_id:
                record.channel_name = record.channel_id.display_name
            else:
                record.channel_name = False

    @api.depends("direction", "channel_name", "timestamp", "request_method")
    def _compute_display_name(self):
        """Compute display name."""
        for record in self:
            parts = []
            if record.direction:
                parts.append(record.direction.upper()[:2])
            if record.request_method:
                parts.append(record.request_method)
            if record.channel_name:
                parts.append(record.channel_name[:30])
            if record.timestamp:
                parts.append(fields.Datetime.to_string(record.timestamp))

            record.display_name = " | ".join(parts) if parts else f"Event {record.id}"

    @api.depends("request_payload")
    def _compute_payload_hash(self):
        """Compute SHA256 hash of payload for duplicate detection."""
        for record in self:
            if record.request_payload:
                try:
                    parsed = json.loads(record.request_payload)
                    normalized = json.dumps(
                        parsed, sort_keys=True, separators=(",", ":")
                    )
                    record.request_payload_hash = hashlib.sha256(
                        normalized.encode("utf-8"),
                    ).hexdigest()
                except json.JSONDecodeError, ValueError:
                    record.request_payload_hash = hashlib.sha256(
                        record.request_payload.encode("utf-8"),
                    ).hexdigest()
            else:
                record.request_payload_hash = False

    @api.depends("request_payload", "response_payload")
    def _compute_payload_sizes(self):
        """Compute payload sizes in bytes."""
        for record in self:
            record.request_payload_size = (
                len(record.request_payload.encode("utf-8"))
                if record.request_payload
                else 0
            )
            record.response_payload_size = (
                len(record.response_payload.encode("utf-8"))
                if record.response_payload
                else 0
            )

    @api.depends("request_url", "channel_id")
    def _compute_request_endpoint(self):
        """Extract endpoint path from full URL."""
        for record in self:
            if record.request_url and record.channel_id:
                base_url = getattr(record.channel_id, "endpoint_url", "") or ""
                if base_url and record.request_url.startswith(base_url):
                    record.request_endpoint = record.request_url[len(base_url) :]
                else:
                    parsed = urlparse(record.request_url)
                    record.request_endpoint = parsed.path
            else:
                record.request_endpoint = "/"

    @api.depends("status_code")
    def _compute_status_category(self):
        """Categorize HTTP status code."""
        for record in self:
            if not record.status_code:
                record.status_category = "unknown"
            elif 200 <= record.status_code < 300:
                record.status_category = "success"
            elif 300 <= record.status_code < 400:
                record.status_category = "redirect"
            elif 400 <= record.status_code < 500:
                record.status_category = "client_error"
            elif 500 <= record.status_code < 600:
                record.status_category = "server_error"
            else:
                record.status_category = "unknown"

    @api.depends("state", "status_category")
    def _compute_is_success(self):
        """Determine if event was successful."""
        for record in self:
            if record.direction == "inbound":
                record.is_success = record.state == "success"
            else:
                record.is_success = record.status_category in (
                    "success",
                    "redirect",
                )

    @api.depends("duration_ms")
    def _compute_performance_rating(self):
        """Rate performance based on duration."""
        for record in self:
            if not record.duration_ms:
                record.performance_rating = False
            elif record.duration_ms < 100:
                record.performance_rating = "excellent"
            elif record.duration_ms < 500:
                record.performance_rating = "good"
            elif record.duration_ms < 1000:
                record.performance_rating = "average"
            elif record.duration_ms < 3000:
                record.performance_rating = "slow"
            else:
                record.performance_rating = "very_slow"

    # -------------------------------------------------------------------------
    # STATE MANAGEMENT
    # -------------------------------------------------------------------------

    def mark_processing(self):
        """Mark event as currently being processed."""
        self.write({"state": "processing"})

    def mark_success(self):
        """Mark event as successfully processed."""
        self.write(
            {
                "state": "success",
                "date_completed": fields.Datetime.now(),
                "error_message": False,
                "error_type": False,
            },
        )

    def mark_failed(self, error_message, error_type="other", schedule_retry=True):
        """Mark the event as failed and optionally schedule a retry.

        :param error_message: error description
        :param error_type: type of error
        :param schedule_retry: whether to schedule a retry
        """
        self.ensure_one()

        values = {
            "state": "failed",
            "error_message": error_message,
            "error_type": error_type,
            "retry_count": self.retry_count + 1,
        }

        channel = self.channel_id
        if (
            schedule_retry
            and hasattr(channel, "retry_enabled")
            and channel.retry_enabled
        ):
            max_retries = getattr(channel, "retry_max_attempts", 3)

            if self.retry_count < max_retries:
                delay_seconds = channel.calculate_retry_delay(self.retry_count + 1)
                next_retry = fields.Datetime.now() + timedelta(seconds=delay_seconds)
                values["date_next_retry"] = next_retry
                values["state"] = "retry"
                _logger.info(
                    "Event %d failed (attempt %d/%d). Retrying in %ds",
                    self.id,
                    self.retry_count + 1,
                    max_retries,
                    delay_seconds,
                )
            else:
                values["date_completed"] = fields.Datetime.now()
                values["date_next_retry"] = False
                _logger.error(
                    "Event %d permanently failed after %d retries: %s",
                    self.id,
                    self.retry_count,
                    error_message,
                )
        else:
            values["date_completed"] = fields.Datetime.now()

        self.write(values)

    def mark_duplicate(self):
        """Mark event as duplicate."""
        self.write(
            {
                "state": "duplicate",
                "date_completed": fields.Datetime.now(),
                "error_type": "duplicate",
            },
        )

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_retry_now(self) -> dict[str, Any]:
        """Manually retry failed or scheduled event immediately."""
        self.ensure_one()

        if self.state not in ["failed", "pending", "retry"]:
            raise ValidationError(
                self.env._(
                    "Only failed, pending, or scheduled-retry events can be retried"
                )
            )

        self.write(
            {
                "state": "pending",
                "date_next_retry": fields.Datetime.now(),
                "error_message": False,
                "error_type": False,
            },
        )

        if self.direction == "inbound":
            channel = self.channel_id
            if hasattr(channel, "_run_queued_event"):
                # ir.job runs after this transaction commits, so the
                # pending-state write above is visible to the job by
                # construction — no postcommit hook or db_name routing needed.
                channel.delayed()._run_queued_event(self.id)
            else:
                raise ValidationError(
                    self.env._("Channel does not support event processing")
                )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Retry Scheduled"),
                "message": self.env._("Event has been queued for retry"),
                "type": "success",
                "sticky": False,
            },
        }

    def action_view_channel(self) -> dict[str, Any]:
        """View the channel for this event."""
        self.ensure_one()

        if not self.channel_id:
            raise ValidationError(self.env._("No channel associated with this event"))

        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Channel"),
            "res_model": self.channel_id._name,
            "res_id": self.channel_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_related_events(self) -> dict[str, Any] | None:
        """View events with same trace ID."""
        self.ensure_one()

        if not self.trace_id:
            return None

        return {
            "name": self.env._("Related Events"),
            "type": "ir.actions.act_window",
            "res_model": "api.event.log",
            "view_mode": "list,form",
            "domain": [("trace_id", "=", self.trace_id)],
        }

    # -------------------------------------------------------------------------
    # CRON / AUTOVACUUM
    # -------------------------------------------------------------------------

    @api.model
    def _cron_retry_failed_events(self):
        """Scheduled action to retry failed inbound events."""
        now = fields.Datetime.now()

        batch_size = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("api_transport.retry_batch_size", default="100"),
        )

        # Reclaim window: events created by the inbound pipeline have
        # date_next_retry = NULL (they were queued directly, not scheduled), so a
        # "<= now" filter alone would never pick up an event stranded by a full
        # queue or a recycled worker process. Match NULL as well.
        processing_timeout = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("api_transport.retry_processing_timeout", default="300"),
        )

        events_to_retry = self.search(
            [
                ("direction", "=", "inbound"),
                ("state", "in", ["pending", "retry"]),
                "|",
                ("date_next_retry", "=", False),
                ("date_next_retry", "<=", now),
            ],
            limit=batch_size,
        )

        if not events_to_retry:
            return

        _logger.info("Retrying %d failed events", len(events_to_retry))

        for event in events_to_retry:
            try:
                channel = event.channel_id
                if hasattr(channel, "_run_queued_event"):
                    # Push date_next_retry forward before enqueuing so the next
                    # cron tick (every minute) does not re-enqueue an event that
                    # is still being processed — that would double-dispatch the
                    # handler (e.g. post a webhook payment twice). If the worker
                    # silently drops the event, the timeout lets a later tick
                    # reclaim it. The worker's own mark_success/mark_failed sets
                    # the terminal state well before this window elapses.
                    event.date_next_retry = now + timedelta(seconds=processing_timeout)
                    channel.delayed()._run_queued_event(event.id)
                else:
                    _logger.warning(
                        "Channel %s does not implement _run_queued_event()",
                        channel,
                    )
                    event.mark_failed(
                        "Channel does not support event processing",
                        schedule_retry=False,
                    )
            except Exception as e:
                _logger.exception("Failed to queue event %d for retry", event.id)
                event.mark_failed(str(e), schedule_retry=True)

    @api.autovacuum
    def _gc_old_logs(self):
        """Automatic garbage collection of old event logs.

        Uses direct SQL for bulk deletes (much faster than ORM).
        Respects retention settings from system parameters.
        """
        # Get default retention from config
        default_retention = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "api_transport.log_retention_days",
                default="90",
            ),
        )

        if default_retention <= 0:
            return

        cutoff = fields.Datetime.now() - timedelta(days=default_retention)

        # Delete terminal events (success/failed/duplicate) past retention, plus
        # events stranded in pending/retry that never reached a terminal state
        # (a full queue or a recycled worker can leave these forever). `duplicate`
        # rows in particular are a hostile-input growth vector and were never
        # collected before. Capture the ids so the mail.thread side-tables this
        # model carries (this is a mail.thread model) don't accumulate orphans.
        self.env.cr.execute(
            """
            DELETE FROM api_event_log
            WHERE (
                    state IN ('success', 'failed', 'duplicate')
                    AND date_completed < %(cutoff)s
                )
                OR (
                    state IN ('pending', 'retry')
                    AND create_date < %(cutoff)s
                )
            RETURNING id
            """,
            {"cutoff": cutoff},
        )
        deleted_ids = [row[0] for row in self.env.cr.fetchall()]

        if deleted_ids:
            # Reap orphaned chatter for the deleted logs.
            self.env.cr.execute(
                "DELETE FROM mail_message WHERE model = 'api.event.log' "
                "AND res_id = ANY(%s)",
                (deleted_ids,),
            )
            self.env.cr.execute(
                "DELETE FROM mail_followers WHERE res_model = 'api.event.log' "
                "AND res_id = ANY(%s)",
                (deleted_ids,),
            )
            _logger.info(
                "Garbage collected %d event logs older than %d days",
                len(deleted_ids),
                default_retention,
            )

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def get_payload_dict(self) -> dict[str, Any]:
        """Parse request payload as JSON dict."""
        self.ensure_one()
        try:
            return json.loads(self.request_payload) if self.request_payload else {}
        except (json.JSONDecodeError, ValueError) as e:
            _logger.warning("Failed to parse payload for event %d: %s", self.id, e)
            return {}

    @api.model
    def check_duplicate_before_create(
        self,
        channel_ref: str,
        payload_json: str,
        event_id_external: str | None = None,
        dedup_window_hours: int = 1,
    ) -> dict[str, Any]:
        """Check for a duplicate event BEFORE creating a record.

        Centralized dedup (external ID + payload hash); controllers call this
        before creating event logs.

        :param channel_ref: channel reference string (e.g. "remote.device,123")
        :param payload_json: JSON string of the payload
        :param event_id_external: optional external event ID for deduplication
        :param dedup_window_hours: window for payload-hash duplicates (default 1)
        :return: {'is_duplicate': bool, 'duplicate_event_id': int|None,
            'reason': 'external_id'|'payload_hash'}
        :rtype: dict
        """
        # Check 1: Duplicate by external ID (if provided)
        if event_id_external:
            existing_by_external_id = self.search(
                [
                    ("channel_id", "=", channel_ref),
                    ("event_id_external", "=", event_id_external),
                ],
                limit=1,
            )
            if existing_by_external_id:
                _logger.info(
                    "Duplicate event detected by external ID: %s (original event: %s)",
                    event_id_external,
                    existing_by_external_id.id,
                )
                return {
                    "is_duplicate": True,
                    "duplicate_event_id": existing_by_external_id.id,
                    "reason": "external_id",
                }

        # Check 2: Duplicate by payload hash (content-based deduplication)
        try:
            # Compute hash
            parsed = json.loads(payload_json)
            normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

            # Check for recent duplicates
            cutoff = fields.Datetime.now() - timedelta(hours=dedup_window_hours)
            existing_by_hash = self.search(
                [
                    ("channel_id", "=", channel_ref),
                    ("request_payload_hash", "=", payload_hash),
                    ("timestamp", ">=", cutoff),
                ],
                limit=1,
            )
            if existing_by_hash:
                _logger.info(
                    "Duplicate event detected by payload hash: %s... (original event: %s)",
                    payload_hash[:16],
                    existing_by_hash.id,
                )
                return {
                    "is_duplicate": True,
                    "duplicate_event_id": existing_by_hash.id,
                    "reason": "payload_hash",
                }
        except Exception as e:
            _logger.warning("Failed to compute payload hash for deduplication: %s", e)

        # Not a duplicate
        return {
            "is_duplicate": False,
            "duplicate_event_id": None,
            "reason": None,
        }
