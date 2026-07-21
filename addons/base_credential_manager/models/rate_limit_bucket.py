import logging
from datetime import timedelta
from typing import Any

from psycopg import errors as psycopg_errors

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Max 1 hour of token refill applied per consume_token call. Caps forward
# clock skew so a bucket never refills more than one hour's worth of tokens
# in a single tick.
MAX_REFILL_SECONDS = 3600


class RateLimitBucket(models.Model):
    """Generic rate limit token bucket stored in database."""

    # Token bucket: each bucket holds up to rate_limit_requests tokens, refilled
    # at a constant rate derived from the configured window; every request
    # consumes 1 token and is rejected once the bucket is empty. Endpoint models
    # are duck-typed and expected to expose enable_rate_limiting (Boolean),
    # rate_limit_requests (Integer) and either webhook_rate_limit_window (Integer
    # seconds) or rate_limit_period (Selection: second/minute/hour/day) — see
    # _get_endpoint_config for how the window is resolved. Row-level DB locking
    # keeps consume_token atomic across workers.

    _name = "rate.limit.bucket"
    _description = "Rate Limit Token Bucket"
    _rec_name = "bucket_key"

    bucket_key = fields.Char(
        required=True,
        index=True,
        help="Unique key format: model:record_id:company_id or model:record_id:global",
    )
    endpoint_model = fields.Char(
        required=True,
        index=True,
        help="Model name of the rate-limited endpoint (e.g., 'webhook.subscription')",
    )
    endpoint_id = fields.Integer(
        string="Endpoint Record ID",
        required=True,
        index=True,
        help="Database ID of the rate-limited endpoint record",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        index=True,
        help="Company for per-company rate limiting. Empty = endpoint-wide limit.",
    )
    tokens = fields.Float(
        string="Available Tokens",
        default=0.0,
        help="Current number of available tokens in bucket",
    )
    last_refill = fields.Datetime(
        string="Last Refill Time",
        default=fields.Datetime.now,
        help="Timestamp of last token refill",
    )
    last_request_at = fields.Datetime(
        string="Last Request",
        help="Timestamp of last request using this bucket",
    )

    _bucket_key_uniq = models.Constraint(
        "unique(bucket_key)",
        "Rate limit bucket key must be unique!",
    )

    _PERIOD_SECONDS = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }

    def _get_period_seconds(self, period: str) -> int:
        """Convert period string to seconds.

        :raises ValueError: if ``period`` is not a known period key.
        """
        # Raise on unknown values instead of silently defaulting to 60s: a typo
        # in an endpoint's rate_limit_period config should surface immediately —
        # a silent fallback let a 1-character mistake turn a 'day' cap into a
        # 'minute' cap, multiplying the effective limit by 1440 with no notice.
        try:
            return self._PERIOD_SECONDS[period]
        except KeyError as exc:
            raise ValueError(
                f"Unknown rate-limit period {period!r} "
                f"(valid: {sorted(self._PERIOD_SECONDS)})"
            ) from exc

    def _get_endpoint_config(self) -> tuple[int, int, float]:
        """Get rate limit configuration from the endpoint record.

        :return: ``(max_requests, period_seconds, refill_rate)`` — max requests
            per period, window length in seconds, and tokens per second.
        :rtype: tuple[int, int, float]
        """
        self.ensure_one()

        # Validate model exists in registry. A missing model means the owning
        # module was uninstalled while buckets still exist — raise so the
        # caller fails closed (consume_token's except branch handles it).
        if self.endpoint_model not in self.env:
            raise ValueError(
                f"Endpoint model {self.endpoint_model!r} not in registry "
                f"(bucket {self.bucket_key}). The owning module may have "
                f"been uninstalled; GC this bucket."
            )

        endpoint = self.env[self.endpoint_model].browse(self.endpoint_id)
        if not endpoint.exists():
            raise ValueError(
                f"Endpoint {self.endpoint_model}:{self.endpoint_id} not "
                f"found (bucket {self.bucket_key})."
            )

        # Read rate limit configuration. Use explicit None-checks instead of
        # `or` so an intentional zero ("block everything") is preserved rather
        # than flipped to the 100 default.
        max_requests = getattr(endpoint, "rate_limit_requests", None)
        if max_requests is None:
            max_requests = 100

        # base_automation's webhook config stores the window as a raw seconds
        # count (webhook_rate_limit_window), not the period-string contract
        # documented above — no model actually defines rate_limit_period, so
        # reading it here always fell through to a hardcoded "minute" (60s)
        # regardless of the configured window. Prefer the explicit seconds
        # value when present; keep the period-string path as a fallback for
        # any future endpoint model that does implement that contract.
        # ``webhook_rate_limit_window`` is an ORM Integer, so a cleared or
        # zeroed window reads as 0 (never None); a non-positive value is
        # nonsensical as the refill-window denominator — it would give
        # refill_rate=0.0 (a bucket that never refills) or, if negative, a
        # rate that drains tokens over time. Unlike ``max_requests`` above,
        # where 0 is a meaningful "block everything" cap, a non-positive
        # window means "not configured": fall back to the period-string
        # contract.
        period_seconds = getattr(endpoint, "webhook_rate_limit_window", None)
        if period_seconds is None or period_seconds <= 0:
            period = getattr(endpoint, "rate_limit_period", None) or "minute"
            period_seconds = self._get_period_seconds(period)

        refill_rate = (max_requests / period_seconds) if period_seconds else 0.0

        return max_requests, period_seconds, refill_rate

    @api.model
    def get_or_create_bucket(
        self,
        endpoint_record: Any,
        company_id: int | None = None,
    ) -> Any:
        """Get or create the rate limit bucket for an endpoint+company.

        :param endpoint_record: record exposing rate-limit fields (e.g.
            webhook.subscription).
        :param company_id: company id, or None for an endpoint-wide limit.
        :return: the rate.limit.bucket record.
        """
        # Generate bucket key
        company_part = company_id or "global"
        bucket_key = f"{endpoint_record._name}:{endpoint_record.id}:{company_part}"

        # Try to find existing bucket
        bucket = self.search([("bucket_key", "=", bucket_key)], limit=1)
        if bucket:
            return bucket

        # Get capacity from endpoint. None-check preserves an intentional 0.
        max_requests = getattr(endpoint_record, "rate_limit_requests", None)
        if max_requests is None:
            max_requests = 100

        # Two concurrent workers can both miss the search above and race into
        # create(). The unique index on bucket_key protects data integrity but
        # raises UniqueViolation for the loser — we catch it, roll back to a
        # savepoint, and re-read the winning row instead of failing the request.
        # Double-quoted identifier: endpoint_record.id is normally a positive
        # DB row id, but callers may key buckets on a synthetic, non-DB
        # identifier (e.g. mcp_server's per-user bucket uses -1 for
        # anonymous) — an unquoted savepoint name can't contain a bare "-"
        # (SAVEPOINT bucket_create_-1_global is a SQL syntax error).
        # Quoting makes any id/company value safe.
        savepoint = f"bucket_create_{endpoint_record.id}_{company_part}"
        self.env.cr.execute(f'SAVEPOINT "{savepoint}"')
        try:
            bucket = self.create(
                {
                    "bucket_key": bucket_key,
                    "endpoint_model": endpoint_record._name,
                    "endpoint_id": endpoint_record.id,
                    "company_id": company_id,
                    "tokens": max_requests,  # Start with full bucket
                    "last_refill": fields.Datetime.now(),
                },
            )
            self.env.cr.execute(f'RELEASE SAVEPOINT "{savepoint}"')
            _logger.info(
                "Created rate limit bucket: %s (capacity: %d)",
                bucket_key,
                max_requests,
            )
            return bucket
        except psycopg_errors.UniqueViolation:
            self.env.cr.execute(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
            bucket = self.search([("bucket_key", "=", bucket_key)], limit=1)
            if not bucket:
                # Extremely unlikely: unique violation but row not visible.
                # Fall through so the caller sees an empty recordset and the
                # exception surfaces instead of silently returning nothing.
                raise
            return bucket

    # Bounded wait for the row lock in strict mode. If the bucket stays
    # contended past this, we give up and fail CLOSED (deny). Kept short so a
    # security-sensitive caller never hangs on a hot bucket — it denies fast.
    STRICT_LOCK_TIMEOUT_MS = 3000

    def consume_token(self, strict: bool = False) -> bool:
        """Attempt to consume one token from the bucket atomically.

        :param strict: if True, fail CLOSED on lock contention / timeout /
            internal errors (deny); if False (default), fail OPEN (allow).
        :return: True if a token was consumed, False if the rate limit was
            exceeded or the request was denied in strict mode.
        :rtype: bool
        """
        # Locking strategy per mode — pick per caller:
        # * strict=True: SELECT ... FOR UPDATE under a bounded lock_timeout
        #   (STRICT_LOCK_TIMEOUT_MS). The request waits briefly; on timeout the
        #   statement raises and the except branch denies. Use for credential /
        #   auth endpoints so the cap holds under a parallel burst instead of
        #   being silently bypassed.
        # * strict=False (default): SELECT ... FOR UPDATE SKIP LOCKED. A locked
        #   row is skipped and the request allowed — preserves availability for
        #   best-effort callers (webhooks) but a highly-parallel burst CAN exceed
        #   the cap. Never use where the limit is a security control.
        self.ensure_one()

        savepoint_name = f"rate_limit_lock_{self.id}"
        self.env.cr.execute(f"SAVEPOINT {savepoint_name}")

        try:
            # Acquire exclusive lock on this bucket row (atomic!).
            # SECURITY: parameterized query (%s placeholder) prevents injection.
            if strict:
                # Bounded blocking lock. set_config(..., is_local=true) scopes
                # the timeout to the current transaction (like SET LOCAL) while
                # allowing a bound parameter — SET LOCAL itself does not accept
                # placeholders. On contention past the timeout Postgres raises
                # LockNotAvailable, caught below → deny (fail CLOSED). No SKIP
                # LOCKED here: skipping the lock is exactly the silent bypass we
                # must avoid for security-sensitive callers.
                self.env.cr.execute(
                    "SELECT set_config('lock_timeout', %s, true)",
                    [f"{self.STRICT_LOCK_TIMEOUT_MS}ms"],
                )
                self.env.cr.execute(
                    """
                    SELECT id, tokens, last_refill
                    FROM rate_limit_bucket
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    [self.id],
                )
                # Fetch BEFORE resetting lock_timeout: executing another
                # statement first would consume the cursor's result set for
                # that statement instead of this SELECT.
                row = self.env.cr.fetchone()
                # Narrow the tightened timeout to just this lock acquisition.
                # is_local=true scopes it like SET LOCAL (resets at
                # transaction end), but a caller that reaches consume_token()
                # mid-transaction and keeps issuing queries afterward would
                # otherwise run the REST of that transaction under a 3s
                # lock_timeout too. Reset immediately once the lock is held.
                self.env.cr.execute("RESET lock_timeout")
            else:
                # SKIP LOCKED: if the row is locked, skip it instead of waiting.
                # Prevents deadlocks/latency in high-concurrency best-effort
                # scenarios; a skipped lock means we ALLOW the request.
                self.env.cr.execute(
                    """
                    SELECT id, tokens, last_refill
                    FROM rate_limit_bucket
                    WHERE id = %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    [self.id],
                )
                row = self.env.cr.fetchone()
            if not row:
                # Only reachable in non-strict mode: SKIP LOCKED returned no
                # row because another transaction holds the lock. Allow the
                # request (best-effort rate limiting). In strict mode we never
                # get here — FOR UPDATE either returns the row or raises on
                # timeout (handled by the except branch as a DENY).
                self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                if strict:
                    # Defensive: should be unreachable, but never fail open here.
                    _logger.warning(
                        "Rate limit bucket %s locked; denying request (strict mode).",
                        self.bucket_key,
                    )
                    return False
                _logger.debug(
                    "Rate limit bucket %s locked by another transaction, allowing request (best-effort rate limiting).",
                    self.bucket_key,
                )
                return True

            _bucket_id, current_tokens, last_refill = row

            # Get current configuration from endpoint
            capacity, _period, refill_rate = self._get_endpoint_config()

            # Calculate tokens to add based on elapsed time
            now = fields.Datetime.now()
            elapsed_seconds = (now - last_refill).total_seconds()

            # Handle clock skew (both backward and forward)
            if elapsed_seconds < 0:
                # Backward clock skew: don't remove tokens
                _logger.warning(
                    "Backward clock skew detected for bucket %s: elapsed_seconds=%.2f.",
                    self.bucket_key,
                    elapsed_seconds,
                )
                new_tokens = current_tokens
                tokens_to_add = 0
            elif elapsed_seconds > MAX_REFILL_SECONDS:
                # Cap to max refill period
                tokens_to_add = MAX_REFILL_SECONDS * refill_rate
                new_tokens = min(current_tokens + tokens_to_add, capacity)
            else:
                # Normal case: refill based on actual elapsed time
                tokens_to_add = elapsed_seconds * refill_rate
                new_tokens = min(current_tokens + tokens_to_add, capacity)

            # Check if we have at least 1 token available
            if new_tokens >= 1.0:
                # Consume 1 token
                final_tokens = new_tokens - 1.0

                # Update bucket atomically
                self.env.cr.execute(
                    """
                    UPDATE rate_limit_bucket
                    SET tokens = %s,
                        last_refill = %s,
                        last_request_at = %s
                    WHERE id = %s
                    """,
                    [final_tokens, now, now, self.id],
                )

                self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                # The raw UPDATE bypasses the ORM cache — drop the stale
                # values so same-transaction ORM readers (reset_bucket, the
                # bucket list view during tests) see the consumed state.
                self.invalidate_recordset(
                    ["tokens", "last_refill", "last_request_at"],
                )
                return True

            # No tokens available - rate limit exceeded
            _logger.warning(
                "Rate limit EXCEEDED: %s (tokens: %.2f, need: 1.0)",
                self.bucket_key,
                new_tokens,
            )
            self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            return False

        except Exception as e:
            # Rollback to savepoint to prevent transaction corruption
            self.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")

            if strict:
                _logger.error(
                    "Error consuming token from bucket %s: %s. Denying request (strict mode).",
                    self.bucket_key,
                    e,
                )
                return False

            # Log error and allow request to prevent blocking users
            _logger.error(
                "Error consuming token from bucket %s: %s. Allowing request to prevent user-facing errors.",
                self.bucket_key,
                e,
            )
            return True

    def reset_bucket(self) -> None:
        """Reset bucket to full capacity (admin action)"""
        for bucket in self:
            capacity, _period, _refill_rate = bucket._get_endpoint_config()
            bucket.write(
                {
                    "tokens": capacity,
                    "last_refill": fields.Datetime.now(),
                },
            )
            _logger.info(
                "Reset rate limit bucket: %s (capacity: %d)",
                bucket.bucket_key,
                capacity,
            )

    @api.model
    def cron_gc_old_buckets(self) -> int:
        """Garbage-collect rate limit buckets unused for 30 days."""
        # Scheduled action: prevents unbounded growth of the bucket table.
        threshold = fields.Datetime.now() - timedelta(days=30)

        old_buckets = self.search(
            [
                "|",
                ("last_request_at", "=", False),
                ("last_request_at", "<", threshold),
            ],
        )

        count = len(old_buckets)
        if count > 0:
            old_buckets.unlink()
            _logger.info(
                "Cleaned up %d old rate limit buckets (unused for 30+ days)",
                count,
            )

        return count
