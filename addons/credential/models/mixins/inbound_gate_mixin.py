import logging
from typing import Any

from odoo import fields, models
from odoo.exceptions import ValidationError

from ...tools.authentication import (
    CaseInsensitiveHeaders,
    ip_in_allowlist,
    verify_signature,
    verify_timestamp,
)
from ...tools.rate_limiter import get_caller_rate_limiter

_logger = logging.getLogger(__name__)


class InboundGateMixin(models.AbstractModel):
    _name = "inbound.gate.mixin"
    _inherit = ["credential.auth.mixin"]
    _description = "Inbound Request Gate Mixin"

    signature_header = fields.Char(
        default="X-Hub-Signature-256",
        help="HTTP header containing the HMAC signature",
    )
    signature_prefix = fields.Char(
        default="sha256=",
        help="Prefix before signature value (e.g., 'sha256=')",
    )
    verification_method = fields.Char(
        help="Python method path for custom verification (format: 'model.method_name'). "
        "Method signature: method(headers: dict, body: str) -> bool",
    )

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

    ip_whitelist = fields.Text(
        help="Comma-separated list of allowed IPs or CIDRs (e.g., '192.168.1.0/24, 10.0.0.5'). "
        "Leave empty to allow all IPs.",
    )
    max_payload_size = fields.Integer(
        default=1048576,
        help="Maximum allowed payload size for DoS prevention. Default: 1MB",
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
        default=True,
        help="Deny the request when the rate-limit bucket cannot be read "
        "(lock contention, timeout, internal error) instead of allowing it. "
        "Enable wherever the limit is a security control rather than a "
        "best-effort cap.",
    )
    rate_limit_window_seconds = fields.Integer(
        string="Rate Window (s)",
        default=60,
        help="Length of the rate-limit window in seconds.",
    )

    AUTH_MODE_ENFORCE = "enforce"
    AUTH_MODE_AUDIT = "audit"
    AUTH_MODE_OFF = "off"

    _BODY_DEPENDENT_AUTH_TYPES = ("hmac_sha256", "hmac_sha512", "custom")

    def _check_inbound_request(
        self,
        headers: dict[str, Any],
        body: str | bytes | None = None,
        remote_addr: str | None = None,
        mode: str = AUTH_MODE_ENFORCE,
        caller_already_checked: bool = False,
    ) -> tuple[bool, int, str]:
        allowed, status, reason, outcome = self._decide_inbound_request(
            headers,
            body=body,
            remote_addr=remote_addr,
            mode=mode,
            caller_already_checked=caller_already_checked,
        )
        self._note_inbound_verdict(
            allowed,
            status,
            reason,
            outcome,
            headers=headers,
            remote_addr=remote_addr,
            mode=mode,
        )
        return allowed, status, reason

    def _decide_inbound_request(
        self,
        headers: dict[str, Any],
        body: str | bytes | None = None,
        remote_addr: str | None = None,
        mode: str = AUTH_MODE_ENFORCE,
        caller_already_checked: bool = False,
    ) -> tuple[bool, int, str, str]:
        self.ensure_one()
        if mode == self.AUTH_MODE_OFF:
            return True, 200, "", "allowed"

        headers = CaseInsensitiveHeaders(headers)

        if not caller_already_checked:
            allowed, status, reason = self._check_inbound_caller(remote_addr)
            if not allowed:
                return (
                    allowed,
                    status,
                    reason,
                    "caller_limited" if status == 429 else "address_refused",
                )

        if (
            body is not None
            and self.max_payload_size
            and len(body) > self.max_payload_size
        ):
            return (
                False,
                413,
                f"payload too large for {self.display_name}",
                "payload_too_large",
            )

        authenticated, refusal = self._authenticate_inbound_identity(headers, body)
        if authenticated:
            if self.rate_limit_enabled and not self._consume_rate_limit():
                return (
                    False,
                    429,
                    f"rate limit exceeded for {self.display_name}",
                    "rate_limited",
                )
            return True, 200, "", "allowed"

        if mode == self.AUTH_MODE_AUDIT:
            # Carried, not logged here: `_note_inbound_verdict` owns the
            # reporting, and it is the only side that knows whether this
            # admission is news or the same standing condition as the last
            # one. The reason lands on the audit row, which is what makes it
            # answer *why* the request was unauthenticated.
            return (
                True,
                200,
                refusal or "no valid credential presented",
                "audit_accepted",
            )

        if refusal:
            # A non-empty refusal means the gate answered about *itself*: it
            # has no credential to check against, or it authenticates over a
            # body its caller never passed. That is one standing condition
            # repeated per request, not one fact per request, and it needs
            # the opposite handling from a caller who guessed wrong -- so it
            # is a distinct outcome rather than a shade of `unauthenticated`.
            # The status stays 401: changing what a refused caller sees is a
            # wire-contract change and does not belong in the taxonomy.
            return False, 401, refusal, "misconfigured"

        return (
            False,
            401,
            f"unauthenticated request for {self.display_name} from {remote_addr}",
            "unauthenticated",
        )

    def _authenticate_inbound_identity(
        self,
        headers: dict[str, Any],
        body: str | bytes | None,
    ) -> tuple[bool, str]:
        self.ensure_one()

        if body is None and self.auth_type in self._BODY_DEPENDENT_AUTH_TYPES:
            return False, (
                f"{self.display_name} authenticates with {self.auth_type}, "
                f"which verifies the request body, but the caller passed none"
            )

        try:
            return bool(self._authenticate_by_scheme(headers, body)), ""
        except ValidationError as e:
            # Returned, not logged: the caller already reports every verdict,
            # and logging here as well printed each refusal twice.
            return False, f"{self.display_name}: {e}"

    def _authenticate_by_scheme(
        self,
        headers: dict[str, Any],
        body: str | bytes | None = None,
    ) -> bool:
        self.ensure_one()

        if not self.credential_id and self.auth_type not in ("none", "custom"):
            raise ValidationError(
                self.env._("No credential configured for endpoint '%s'")
                % self.display_name,
            )

        if self.timestamp_verification_enabled:
            timestamp_value = headers.get(self.timestamp_header)
            if not timestamp_value:
                # Debug, not warning: which of the caller-side ways a request
                # failed is a detail you raise the level to get, and the
                # refusal itself is already on the record. At warning level
                # these three are a per-request line whose volume the caller
                # chooses -- the same flood the audit path was fixed for.
                _logger.debug(
                    "Missing timestamp header '%s' for %s",
                    self.timestamp_header,
                    self.display_name,
                )
                return False
            if not verify_timestamp(
                timestamp_value=timestamp_value,
                max_age_seconds=self.timestamp_max_age_seconds,
                env=self.env,
            ):
                _logger.debug(
                    "Timestamp verification failed for %s", self.display_name
                )
                return False

        if self.auth_type == "none":
            return True

        if self.auth_type in ("bearer", "api_key"):
            token = self._presented_token(headers)
            if not token:
                _logger.debug("No bearer token presented for %s", self.display_name)
                return False
            return self.is_valid_token(token)

        secret = None
        if self.auth_type in ("hmac_sha256", "hmac_sha512"):
            secret = self.credential_id._get_verification_secret()

        return verify_signature(
            signature_type=self.auth_type,
            headers=headers,
            body=body or "",
            secret=secret,
            signature_header=self.signature_header,
            signature_prefix=self.signature_prefix,
            verification_method=self.verification_method,
            env=self.env,
        )

    def _presented_token(self, headers: dict[str, Any]) -> str:
        auth_header = headers.get("Authorization") or ""
        if auth_header[:7].lower() == "bearer ":
            return auth_header[7:].strip()
        return (headers.get("X-Device-Token") or "").strip()

    log_inbound_access = fields.Boolean(
        string="Log Every Inbound Request",
        default=False,
        help="Record admitted requests as well as refused ones. Refusals are "
        "always recorded. Turn this on only for an endpoint whose traffic you "
        "want a row per call for — a device reporting once per position fix "
        "will fill the table.",
    )

    def _note_inbound_verdict(
        self,
        allowed: bool,
        status: int,
        reason: str,
        outcome: str,
        headers: Any = None,
        remote_addr: str | None = None,
        mode: str = AUTH_MODE_ENFORCE,
    ) -> None:
        if mode == self.AUTH_MODE_OFF:
            return
        if outcome == "allowed" and not self.log_inbound_access:
            return

        try:
            is_news = self._store_inbound_verdict(
                outcome,
                allowed=allowed,
                status=status,
                reason=reason,
                headers=headers,
                remote_addr=remote_addr,
                mode=mode,
            )
        except Exception:
            _logger.exception(
                "Could not record the inbound verdict for %s; the decision "
                "itself stands and was %s",
                self.display_name,
                "allow" if allowed else "refuse",
            )
            return

        if not is_news:
            # The same standing condition as the row already on file. It was
            # counted; saying so again per request is what turned one fleet
            # into five figures of identical log lines a day.
            return

        if outcome == "audit_accepted":
            _logger.warning(
                "UNAUTHENTICATED request accepted for %s from %s (audit mode): "
                "%s. Provision the credential, then switch to 'enforce'.",
                self.display_name,
                remote_addr,
                reason,
            )
        elif outcome == "misconfigured":
            _logger.error(
                "%s is refusing EVERY request and will keep doing so until it "
                "is fixed: %s. Callers see a 401, so this reads to them as "
                "their credentials being wrong.",
                self.display_name,
                reason,
            )

    # Outcomes whose repeat rate is set by the fleet or by the caller rather
    # than by anything the gate can tell apart. Each folds onto one standing
    # row within its window, carrying `attempt_count` and `last_seen_at`.
    #
    # `unauthenticated` is deliberately absent: two bad tokens are two facts,
    # and an operator reading the trail needs to see both attempts. Its
    # sibling `misconfigured` is present for the mirror-image reason -- the
    # gate answers identically to every caller until somebody fixes it.
    _COALESCED_OUTCOMES = ("caller_limited", "audit_accepted", "misconfigured")

    # Of those, the ones whose standing row is *counted*. Counting means an
    # UPDATE of a row shared by concurrent requests, and this deployment has
    # already measured what that costs on an ingest path: every Odoo cursor
    # runs REPEATABLE READ, under which two transactions updating one row
    # conflict whatever columns they touch, and serialising the writers does
    # not help -- the waiter wakes holding a snapshot older than the winner's
    # commit and conflicts anyway. Only not writing the row works.
    #
    # A caller-rate-limit refusal is rare and its count is the whole signal,
    # so it keeps the counter. An audit-mode admission arrives once per
    # position fix per device: its row is opened when the window opens and
    # never written again, so the hot path only ever reads and inserts.
    _COUNTED_OUTCOMES = ("caller_limited",)

    # Of those, the ones the caller's address is part of the identity of.
    # Which address is being rate-limited *is* the fact, so two addresses
    # hitting the limit are two rows. An audit-mode admission is the
    # opposite: the fact is that this gate has no credential, and whichever
    # address happened to arrive first is incidental. Keying it by address
    # defeats the collapse outright against a sender behind a rotating
    # egress pool -- measured on the GPS fleet, five consecutive fixes
    # produced five rows from five addresses across two gates.
    _COALESCED_PER_CALLER = ("caller_limited",)

    STANDING_WINDOW_PARAM = "credential.inbound_standing_window_seconds"
    STANDING_WINDOW_DEFAULT = 3600

    def _inbound_coalesce_window(self, outcome: str) -> int:
        """Seconds over which repeats of `outcome` fold onto one row.

        A caller-rate-limit refusal is *about* the limiter's window, so it
        uses that one. The other two are not about any window at all: an
        audit-mode admission and a misconfigured gate each report a standing
        state that will read identically on every request until somebody
        changes the configuration. Their window is therefore an operator
        granularity -- how often you want to be told -- and an hour by
        default. A fleet reporting once per position fix would otherwise
        write a row, and print a line, per fix.
        """
        if outcome == "caller_limited":
            return self.rate_limit_window_seconds or 60
        window = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int(self.STANDING_WINDOW_PARAM, self.STANDING_WINDOW_DEFAULT)
        )
        # The parameter tunes how often the condition is reported, not
        # whether it is collapsed at all: a window of zero would put a row
        # and a warning back on every position fix, which is the thing this
        # exists to prevent.
        return max(60, window)

    def _store_inbound_verdict(
        self,
        outcome: str,
        allowed: bool,
        status: int,
        reason: str,
        headers: Any,
        remote_addr: str | None,
        mode: str,
    ) -> bool:
        """Record the verdict. True when this opened a new row.

        False means an identical standing condition was already on record and
        only its counter moved -- which is also the signal the caller uses to
        decide whether the verdict is worth a log line.
        """
        logs = self.env["inbound.access.log"].sudo()
        now = fields.Datetime.now()

        if outcome in self._COALESCED_OUTCOMES:
            window = self._inbound_coalesce_window(outcome)
            domain = [
                ("gate_model", "=", self._name),
                ("gate_id", "=", self.id),
                ("outcome", "=", outcome),
                ("timestamp", ">=", fields.Datetime.subtract(now, seconds=window)),
            ]
            if outcome in self._COALESCED_PER_CALLER:
                domain.append(("source_ip", "=", remote_addr or False))
            standing = logs.search(domain, order="timestamp desc", limit=1)
            if standing:
                if outcome in self._COUNTED_OUTCOMES:
                    standing.write(
                        {
                            "attempt_count": standing.attempt_count + 1,
                            "last_seen_at": now,
                        }
                    )
                return False

        logs.create(
            {
                "gate_model": self._name,
                "gate_id": self.id,
                "gate_name": self.display_name,
                "company_id": self._inbound_company_id(),
                "timestamp": now,
                "last_seen_at": now,
                "allowed": allowed,
                "outcome": outcome,
                "status_code": status,
                "reason": reason or False,
                "source_ip": remote_addr or False,
                "user_agent": (headers or {}).get("User-Agent") or False,
                "auth_type": self.auth_type or False,
                "mode": mode,
            }
        )
        return True

    def _inbound_company_id(self):
        company = self._fields.get("company_id") and self.company_id
        return company.id if company else False

    def _check_inbound_caller(self, remote_addr) -> tuple[bool, int, str]:
        self.ensure_one()
        if self.ip_whitelist and not ip_in_allowlist(remote_addr, self.ip_whitelist):
            return False, 403, f"IP {remote_addr} not allowed for {self.display_name}"

        if self.rate_limit_enabled and not self._consume_caller_allowance(remote_addr):
            return False, 429, f"caller rate limit exceeded for {self.display_name}"

        return True, 200, ""

    PREAUTH_MULTIPLIER_PARAM = "credential.inbound_preauth_multiplier"
    PREAUTH_MULTIPLIER_DEFAULT = 10

    def _consume_caller_allowance(self, remote_addr) -> bool:
        self.ensure_one()
        if not remote_addr:
            return True

        multiplier = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                self.PREAUTH_MULTIPLIER_PARAM,
                default=self.PREAUTH_MULTIPLIER_DEFAULT,
            )
        )
        if multiplier <= 0:
            return True

        limit = max(1, (self.rate_limit_requests or 0) * multiplier)
        window = self.rate_limit_window_seconds or 60
        result = get_caller_rate_limiter(self.env).check(
            (self._name, self.id, remote_addr),
            limit=limit,
            window_seconds=window,
        )
        if not result["allowed"]:
            _logger.warning(
                "Pre-auth rate limit exceeded for %s from %s: %s/%s in %ss",
                self.display_name,
                remote_addr,
                result["attempts"],
                result["limit"],
                window,
            )
        return result["allowed"]

    def _consume_rate_limit(self) -> bool:
        self.ensure_one()
        return self.env["rate.limit.bucket"].consume_for(
            self,
            self._inbound_company_id(),
            strict=bool(self.rate_limit_strict),
        )

    def is_ip_allowed(self, source_ip: str) -> bool:
        self.ensure_one()
        return ip_in_allowlist(source_ip, self.ip_whitelist)
