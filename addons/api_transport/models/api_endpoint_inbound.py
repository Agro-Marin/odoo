import json
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.api_transport.tools import (
    get_event_queue,
    verify_signature,
    verify_timestamp,
    worker_env,
)
from odoo.addons.base_credential_manager.tools import ip_in_allowlist

_logger = logging.getLogger(__name__)


class ApiEndpointInbound(models.AbstractModel):
    """Abstract model for inbound HTTP endpoints.

    Extends api.channel.mixin with HMAC verification, IP whitelisting, payload
    limits, duplicate + timestamp (replay) checks and async/sync processing.
    Concrete models inherit ['api.endpoint.inbound', 'mail.thread'].
    """

    _name = "api.endpoint.inbound"
    _inherit = ["api.channel.mixin"]
    _description = "Inbound Endpoint"

    # ==================== Authentication (restricted to verifiable types) ====================

    # auth_type is inherited unchanged from api.channel.mixin. The mixin's base
    # selection deliberately holds only the inbound-safe types that
    # verify_signature() implements; basic and oauth2 are outbound-only (no
    # inbound verifier exists for them) and are added back exclusively on
    # api.endpoint.outbound via selection_add. Exposing them here would let an
    # admin configure an endpoint that silently rejects every request.

    # ==================== HMAC Configuration ====================

    signature_header = fields.Char(
        default="X-Hub-Signature-256",
        help="HTTP header containing the HMAC signature",
    )
    signature_prefix = fields.Char(
        default="sha256=",
        help="Prefix before signature value (e.g., 'sha256=')",
    )

    # ==================== Custom Verification ====================

    verification_method = fields.Char(
        help="Python method path for custom verification (format: 'model.method_name'). "
        "Method signature: method(headers: dict, body: str) -> bool",
    )
    ip_whitelist = fields.Text(
        help="Comma-separated list of allowed IPs or CIDRs (e.g., '192.168.1.0/24, 10.0.0.5'). "
        "Leave empty to allow all IPs.",
    )

    # ==================== Payload Limits ====================

    max_payload_size = fields.Integer(
        default=1048576,  # 1MB
        help="Maximum allowed payload size for DoS prevention. Default: 1MB",
    )

    # ==================== Duplicate Detection ====================

    duplicate_detection_enabled = fields.Boolean(
        default=True,
        help="Prevent duplicate event processing using payload hash",
    )
    duplicate_window_seconds = fields.Integer(
        default=60,
        help="Time window for duplicate detection",
    )

    # ==================== Timestamp Verification ====================

    timestamp_verification_enabled = fields.Boolean(
        default=False,
        help="Enable timestamp verification to prevent replay attacks",
    )
    timestamp_header = fields.Char(
        default="X-Webhook-Timestamp",
        help="HTTP header containing the request timestamp",
    )
    timestamp_max_age_seconds = fields.Integer(
        default=300,
        help="Maximum age of request timestamp. Default: 5 minutes",
    )

    # ==================== Processing Configuration ====================

    processing_mode = fields.Selection(
        selection=[
            ("sync", "Synchronous"),
            ("async", "Asynchronous"),
        ],
        default="async",
        required=True,
        help="Sync: Process immediately. Async: Queue for background processing.",
    )

    # ==================== Event Logging ====================

    event_log_ids = fields.One2many(
        comodel_name="api.event.log",
        compute="_compute_event_log_ids",
    )
    event_count = fields.Integer(
        compute="_compute_event_count",
    )

    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------

    @api.constrains("max_payload_size")
    def _check_max_payload_size(self):
        """Validate max payload size is reasonable."""
        max_limit = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("api_transport.max_payload_size_limit", default="104857600"),
        )

        for record in self:
            if record.max_payload_size <= 0:
                raise ValidationError(
                    self.env._("Max payload size must be greater than 0")
                )
            if record.max_payload_size > max_limit:
                max_mb = max_limit / (1024 * 1024)
                raise ValidationError(
                    self.env._(
                        "Max payload size cannot exceed %(max_mb).0fMB (%(max_bytes)d bytes)",
                        max_mb=max_mb,
                        max_bytes=max_limit,
                    ),
                )

    @api.constrains("duplicate_window_seconds")
    def _check_duplicate_window(self):
        """Validate duplicate detection window."""
        max_window = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "api_transport.max_duplicate_window_seconds", default="3600"
            ),
        )

        for record in self:
            if record.duplicate_detection_enabled:
                if record.duplicate_window_seconds <= 0:
                    raise ValidationError(
                        self.env._("Duplicate detection window must be greater than 0"),
                    )
                if record.duplicate_window_seconds > max_window:
                    raise ValidationError(
                        self.env._(
                            "Duplicate detection window cannot exceed %(max)d seconds",
                            max=max_window,
                        ),
                    )

    @api.constrains("auth_type", "verification_method")
    def _check_custom_verification(self):
        """Validate custom verification method format."""
        for record in self:
            if record.auth_type == "custom":
                if not record.verification_method:
                    raise ValidationError(
                        self.env._(
                            "Custom verification method is required when auth type is 'custom'"
                        ),
                    )

                if "." not in record.verification_method:
                    raise ValidationError(
                        self.env._(
                            "Verification method must be in format 'model_name.method_name'"
                        ),
                    )

                parts = record.verification_method.rsplit(".", 1)
                if len(parts) != 2:
                    raise ValidationError(
                        self.env._("Invalid verification method format: '%s'")
                        % record.verification_method,
                    )

                model_name, method_name = parts

                # The runtime gate in _verify_custom (base_credential_manager)
                # only invokes methods named verify_*/_verify_* — custom
                # verification runs under sudo(), so any other name is
                # rejected at request time. Surface that at save time too.
                if not method_name.lstrip("_").startswith("verify_"):
                    raise ValidationError(
                        self.env._(
                            "Verification method name must start with "
                            "'verify_' or '_verify_' (got '%s'). Custom "
                            "verification runs with elevated rights and only "
                            "dedicated verify methods may be invoked.",
                        )
                        % method_name,
                    )

                if model_name not in self.env:
                    raise ValidationError(
                        self.env._("Model '%s' does not exist") % model_name,
                    )

                model_obj = self.env[model_name]
                if not hasattr(model_obj, method_name):
                    raise ValidationError(
                        self.env._(
                            "Method '%(method)s' not found in model '%(model)s'",
                            method=method_name,
                            model=model_name,
                        ),
                    )

                method = getattr(model_obj, method_name)
                if not callable(method):
                    raise ValidationError(
                        self.env._(
                            "'%(model)s.%(method)s' is not callable",
                            model=model_name,
                            method=method_name,
                        ),
                    )

    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------

    def unlink(self) -> bool:
        """Delete endpoint and cascade-delete related event logs."""
        endpoint_refs = [f"{record._name},{record.id}" for record in self]

        event_logs = (
            self.env["api.event.log"]
            .sudo()
            .search([("channel_id", "in", endpoint_refs)])
        )

        if event_logs:
            _logger.info(
                "Deleting %d event logs for %d endpoints",
                len(event_logs),
                len(self),
            )
            event_logs.unlink()

        return super().unlink()

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    def _compute_event_log_ids(self):
        """Get event logs for this endpoint.

        One _read_group per compute instead of one search per record —
        avoids N+1 when the list view renders many endpoints.
        """
        logs_by_ref: dict[str, list[int]] = {}
        if self.ids:
            endpoint_refs = [f"{record._name},{record.id}" for record in self]
            groups = self.env["api.event.log"]._read_group(
                domain=[
                    ("channel_id", "in", endpoint_refs),
                    ("direction", "=", "inbound"),
                ],
                groupby=["channel_id"],
                aggregates=["id:recordset"],
            )
            for ref, recordset in groups:
                logs_by_ref[ref] = recordset.ids
        for record in self:
            ref = f"{record._name},{record.id}"
            record.event_log_ids = [(6, 0, logs_by_ref.get(ref, []))]

    def _compute_event_count(self):
        """Count events for this endpoint.

        One _read_group per compute instead of one search_count per
        record — avoids N+1 when the list view renders many endpoints.
        """
        counts_by_ref: dict[str, int] = {}
        if self.ids:
            endpoint_refs = [f"{record._name},{record.id}" for record in self]
            groups = self.env["api.event.log"]._read_group(
                domain=[
                    ("channel_id", "in", endpoint_refs),
                    ("direction", "=", "inbound"),
                ],
                groupby=["channel_id"],
                aggregates=["__count"],
            )
            counts_by_ref = dict(groups)
        for record in self:
            record.event_count = counts_by_ref.get(f"{record._name},{record.id}", 0)

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def authenticate_request(
        self,
        headers: dict[str, Any],
        body: str | bytes | None = None,
    ) -> bool:
        """Authenticate an inbound request.

        :param headers: HTTP request headers
        :param body: raw request body (bytes preferred; required for HMAC)
        :return: True if authentication succeeded
        :rtype: bool
        """
        self.ensure_one()

        if not self.credential_id and self.auth_type not in ("none", "custom"):
            raise ValidationError(
                self.env._("No credential configured for endpoint '%s'")
                % self.display_name,
            )

        # Verify timestamp first (replay attack prevention)
        if self.timestamp_verification_enabled:
            timestamp_value = headers.get(self.timestamp_header)
            if not timestamp_value:
                _logger.warning(
                    "Missing timestamp header '%s' for endpoint %s",
                    self.timestamp_header,
                    self.display_name,
                )
                return False

            if not verify_timestamp(
                timestamp_value=timestamp_value,
                max_age_seconds=self.timestamp_max_age_seconds,
            ):
                _logger.warning(
                    "Timestamp verification failed for endpoint %s",
                    self.display_name,
                )
                return False

        # Shared-secret schemes are verified by digest, never by decryption.
        #
        # ``credential.credential`` rate-limits reads of ``credential_value`` at
        # 100 per user per hour, and every anonymous inbound request runs as the
        # same public user — so decrypting here throttled a correctly
        # provisioned device to 100 requests/hour and answered the 101st with
        # "Invalid credentials", 60x tighter than the endpoint's own configured
        # limit and reported as the wrong failure. ``verify_token`` compares
        # ``credential_fingerprint`` instead: no decryption, no budget spent.
        if self.auth_type in ("bearer", "api_key"):
            is_valid = self._verify_bearer_headers(headers)
            if is_valid and self.credential_id:
                self.credential_id.mark_as_used()
            return is_valid

        # HMAC still needs the secret itself: the digest is computed over the
        # request body, so there is nothing to compare a stored fingerprint to.
        secret = None
        if self.auth_type in ("hmac_sha256", "hmac_sha512"):
            secret = self.credential_id.credential_value

        # Verify signature
        is_valid = verify_signature(
            signature_type=self.auth_type,
            headers=headers,
            body=body or "",
            secret=secret,
            signature_header=self.signature_header,
            signature_prefix=self.signature_prefix,
            verification_method=self.verification_method,
        )

        if is_valid and self.credential_id:
            self.credential_id.mark_as_used()

        return is_valid

    def _verify_bearer_headers(self, headers: dict[str, Any]) -> bool:
        """Verify the bearer/api-key token carried by ``headers``.

        :param headers: HTTP request headers.
        :return: True when the presented token is this endpoint's secret.
        :rtype: bool
        """
        self.ensure_one()
        token = self._presented_token(headers)
        if not token:
            _logger.warning(
                "No bearer token presented for endpoint %s", self.display_name
            )
            return False
        return self.verify_token(token)

    @api.model
    def _presented_token(self, headers: dict[str, Any]) -> str:
        """Extract the shared secret a caller presented.

        ``Authorization: Bearer <token>`` is the contract. ``X-Device-Token`` is
        accepted as a documented fallback because some trackers cannot set an
        Authorization header at all; it was already honoured by the GPS webhook
        and is lifted here so every inbound route agrees on what a token is.

        :param headers: HTTP request headers.
        :return: the presented secret, or '' when none was sent.
        :rtype: str
        """
        auth_header = headers.get("Authorization") or ""
        if auth_header[:7].lower() == "bearer ":
            return auth_header[7:].strip()
        return (headers.get("X-Device-Token") or "").strip()

    # Enforcement modes for :meth:`check_inbound_auth`.
    AUTH_MODE_ENFORCE = "enforce"
    AUTH_MODE_AUDIT = "audit"
    AUTH_MODE_OFF = "off"

    @api.model
    def _inbound_auth_mode(self, parameter_key: str) -> str:
        """Return the enforcement mode for a family of inbound routes.

        ``enforce`` (the shipped default) refuses a request that presents no
        valid token; ``audit`` accepts it but logs a warning naming the
        endpoint; ``off`` skips the check. ``audit`` exists so an upgrade cannot
        silently drop telemetry from hardware already in the field: provision
        the credentials, wait for the audit log to fall quiet, then switch.

        :param parameter_key: the ``ir.config_parameter`` holding the mode.
        :rtype: str
        """
        mode = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(parameter_key, default=self.AUTH_MODE_ENFORCE)
        )
        if mode not in (
            self.AUTH_MODE_ENFORCE,
            self.AUTH_MODE_AUDIT,
            self.AUTH_MODE_OFF,
        ):
            _logger.warning(
                "Unknown value %r for %s; falling back to 'enforce'",
                mode,
                parameter_key,
            )
            return self.AUTH_MODE_ENFORCE
        return mode

    def check_inbound_auth(
        self,
        headers: dict[str, Any],
        remote_addr: str,
        mode: str = AUTH_MODE_ENFORCE,
    ) -> tuple[bool, str]:
        """Decide whether an inbound request on this endpoint may proceed.

        The single gate for every hand-rolled inbound route in the family: IP
        allow-list, then rate limit, then token. Checking the address and the
        limit before the token means an unauthorized source is throttled without
        learning whether its credentials would have been accepted.

        :param headers: HTTP request headers.
        :param remote_addr: source IP address.
        :param mode: one of ``enforce`` / ``audit`` / ``off``.
        :return: ``(allowed, reason)``; ``reason`` is for the log, never for the
            caller — a refusal that varies by cause is an enumeration oracle.
        :rtype: tuple
        """
        self.ensure_one()
        if mode == self.AUTH_MODE_OFF:
            return True, ""

        if self.ip_whitelist and not self.validate_ip_address(remote_addr):
            return False, f"IP {remote_addr} not allowed for {self.display_name}"

        if self.rate_limit_enabled and not self.check_rate_limit():
            return False, f"rate limit exceeded for {self.display_name}"

        # Digest comparison — see _compute_credential_fingerprint for why this
        # must never become a decryption.
        if self.verify_token(self._presented_token(headers)):
            return True, ""

        if mode == self.AUTH_MODE_AUDIT:
            _logger.warning(
                "UNAUTHENTICATED request accepted for %s from %s (audit mode). "
                "Provision the endpoint's token, then switch to 'enforce'.",
                self.display_name,
                remote_addr,
            )
            return True, ""

        return (
            False,
            f"unauthenticated request for {self.display_name} from {remote_addr}",
        )

    def _get_event_handler_callback(self) -> Callable[[int], None]:
        """Return the handler callback for async event processing.

        The callback runs in a worker thread; since Odoo's ORM is not
        thread-safe, an overriding handler that needs DB access MUST create its
        own cursor (Odoo 19+: ``from odoo.modules.registry import Registry``,
        as ``odoo.registry()`` was removed). Prefer overriding
        :meth:`_process_queued_event`. See ``remote.models.remote_device`` for
        a working example.

        :return: a function taking ``event_id``
        :rtype: Callable
        """
        # The default is NOT a placeholder: it opens its own worker environment
        # and dispatches to :meth:`_process_queued_event`, the documented
        # extension point. It used to only log, which meant any caller that
        # enqueued without ``db_name`` — and therefore missed the queue's
        # _run_with_cursor bridge — discarded the payload while the controller
        # answered "202 Accepted". Both routes now end in the same handler, so
        # forgetting ``db_name`` costs an extra cursor, not the data.
        db_name = self.env.cr.dbname
        model_name = self._name
        record_id = self.id

        def _handle(event_id):
            with worker_env(db_name) as worker:
                event = worker["api.event.log"].browse(event_id).exists()
                if not event:
                    _logger.warning("Queued event %s no longer exists", event_id)
                    return
                worker[model_name].browse(record_id)._process_queued_event(event)

        return _handle

    def _process_queued_event(self, event):
        """Process a queued event with a thread-safe Environment (override this).

        Called by the queue worker with an ``api.event.log`` record that already
        has a valid cursor/Environment. Preferred async extension point over
        :meth:`_get_event_handler_callback` (no manual cursor management).

        :param event: api.event.log record (with a valid env)
        """
        _logger.info(
            "Processing event %d for %s - override _process_queued_event()",
            event.id,
            self.display_name,
        )

    def queue_event(
        self,
        payload: dict[str, Any] | str | None = None,
        metadata: dict[str, Any] | None = None,
        event_log: models.Model | None = None,
    ) -> models.Model:
        """Queue an event for processing.

        :param payload: event payload data
        :param metadata: optional metadata (source_ip, headers, etc.)
        :param event_log: existing api.event.log record to reuse
        :return: the api.event.log record
        :rtype: api.event.log
        """
        self.ensure_one()

        if event_log:
            event = event_log
        else:
            payload_str: str
            if isinstance(payload, str):
                payload_str = payload
            elif isinstance(payload, dict):
                payload_str = json.dumps(payload)
            else:
                payload_str = json.dumps({"data": payload})

            event = self.env["api.event.log"].create(
                {
                    "direction": "inbound",
                    "channel_id": f"{self._name},{self.id}",
                    "request_payload": payload_str,
                    "source_ip": (metadata.get("source_ip") if metadata else None),
                    "state": "pending",
                },
            )

        if self.processing_mode == "async":
            # Enqueue only AFTER the current transaction commits. Worker threads
            # open their own cursor and re-read the event by id; if we enqueued
            # here, a worker could dequeue and browse(event_id) before this
            # transaction commits — the row would not yet be visible, the
            # handler would no-op ("event not found"), and the event would stay
            # pending until the recovery cron. A rollback would likewise leave a
            # stale id in the queue. Post-commit enqueue makes the row visible
            # the instant it is queued.
            # ``db_name`` is REQUIRED, not optional: it is what selects the
            # worker's _run_with_cursor branch, which re-browses the event on a
            # fresh cursor and dispatches to :meth:`_process_queued_event`.
            # Omitting it makes the worker call the raw callback instead — and
            # the default callback below only logs, so every payload of every
            # endpoint that overrides _process_queued_event (rather than
            # _get_event_handler_callback) was silently discarded while the
            # controller answered "202 Accepted".
            # No ``uid``: the worker environment defaults to SUPERUSER_ID. The
            # request that queued the event is usually the public user (inbound
            # routes are auth="public"), and worker_env() builds a plain
            # Environment with no ``su`` flag — handing it that uid would make
            # every handler fail on access rights.
            queue = get_event_queue()
            callback = self._get_event_handler_callback()
            event_id = event.id
            db_name = self.env.cr.dbname
            self.env.cr.postcommit.add(
                lambda: queue.queue(event_id, callback, db_name=db_name)
            )

        self.update_date_last_activity()

        return event

    # -------------------------------------------------------------------------
    # VALIDATIONS
    # -------------------------------------------------------------------------

    def check_duplicate_event(
        self,
        payload_hash: str,
        exclude_event_id: int | None = None,
    ) -> bool:
        """Return whether an event with the same payload hash was recently received.

        :param payload_hash: SHA256 hash of the payload
        :param exclude_event_id: event ID to exclude from the search
        :return: True if a duplicate was found
        :rtype: bool
        """
        self.ensure_one()

        if not self.duplicate_detection_enabled:
            return False

        now = fields.Datetime.now()
        since = now - timedelta(seconds=self.duplicate_window_seconds)

        endpoint_ref = f"{self._name},{self.id}"

        domain = [
            ("channel_id", "=", endpoint_ref),
            ("request_payload_hash", "=", payload_hash),
            ("timestamp", ">=", since),
        ]

        if exclude_event_id:
            domain.append(("id", "!=", exclude_event_id))

        return self.env["api.event.log"].sudo().search_count(domain) > 0

    def validate_ip_address(self, source_ip: str) -> bool:
        """Return whether the source IP is allowed by the whitelist.

        The check is shared with base_automation's webhook rules (see
        base_credential_manager.tools.ip_in_allowlist). That helper fails closed
        on an empty list while this method historically returned True; callers
        guard with ``if endpoint.ip_whitelist and not ...``, which is where
        "unrestricted when unconfigured" belongs and where it already was.

        :param source_ip: source IP address
        :return: True if the IP is allowed
        :rtype: bool
        """
        self.ensure_one()
        return ip_in_allowlist(source_ip, self.ip_whitelist)
