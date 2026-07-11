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
    """Generic rate limit token bucket stored in database.

    Uses token bucket algorithm:
    - Bucket has maximum capacity (rate_limit_requests)
    - Tokens refill at constant rate (based on rate_limit_period)
    - Each request consumes 1 token
    - Request rejected if no tokens available

    Works with any model that has these fields:
    - enable_rate_limiting (Boolean)
    - rate_limit_requests (Integer) - max requests per period
    - rate_limit_period (Selection) - 'second', 'minute', 'hour', 'day'

    Database-level locking ensures atomicity across workers.
    """

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

        Raises on unknown values instead of silently defaulting to 60s.
        A typo in an endpoint's rate_limit_period config should surface
        immediately — silent fallback meant a 1-character mistake could
        turn a 'day' cap into a 'minute' cap, multiplying the effective
        limit by 1440 without any operator notice.
        """
        try:
            return self._PERIOD_SECONDS[period]
        except KeyError as exc:
            raise ValueError(
                f"Unknown rate-limit period {period!r} "
                f"(valid: {sorted(self._PERIOD_SECONDS)})"
            ) from exc

    def _get_endpoint_config(self) -> tuple[int, str, float]:
        """Get rate limit configuration from endpoint record.

        Returns:
            tuple: (max_requests, period, refill_rate)
                - max_requests (int): Maximum requests per period
                - period (str): Time period ('second', 'minute', 'hour', 'day')
                - refill_rate (float): Tokens per second

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
        # `or` so an intentional zero ("block everything") is preserved —
        # the previous `or 100` silently flipped a zero cap to 100.
        max_requests = getattr(endpoint, "rate_limit_requests", None)
        if max_requests is None:
            max_requests = 100
        period = getattr(endpoint, "rate_limit_period", None) or "minute"

        period_seconds = self._get_period_seconds(period)
        refill_rate = (max_requests / period_seconds) if period_seconds else 0.0

        return max_requests, period, refill_rate

    @api.model
    def get_or_create_bucket(
        self,
        endpoint_record: Any,
        company_id: int | None = None,
    ) -> Any:
        """Get or create rate limit bucket for endpoint+company.

        Args:
            endpoint_record: Record with rate limit fields (e.g., webhook.subscription)
            company_id: Company ID (or None for endpoint-wide limit)

        Returns:
            rate.limit.bucket record

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
        savepoint = f"bucket_create_{endpoint_record.id}_{company_part}"
        self.env.cr.execute(f"SAVEPOINT {savepoint}")
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
            self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint}")
            _logger.info(
                "Created rate limit bucket: %s (capacity: %d)",
                bucket_key,
                max_requests,
            )
            return bucket
        except psycopg_errors.UniqueViolation:
            self.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
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
        """Attempt to consume one token from bucket (atomic operation).

        Two locking strategies, selected by ``strict``:

        * **strict=True (fail CLOSED)** — plain ``SELECT ... FOR UPDATE`` under
          a bounded ``lock_timeout`` (:attr:`STRICT_LOCK_TIMEOUT_MS`). The
          request WAITS briefly for the lock; if it can't get it in time the
          statement raises, which the exception handler turns into a DENY.
          This is the correct choice for credential-access / auth endpoints:
          under a parallel burst the cap is enforced, never silently bypassed.

        * **strict=False (fail OPEN, default)** — ``SELECT ... FOR UPDATE SKIP
          LOCKED``. If another transaction holds the row we skip it and ALLOW
          the request. This preserves availability for best-effort callers
          (e.g. webhooks) but means a highly-parallel burst CAN exceed the cap,
          because contending requests are waved through instead of counted.
          Do NOT use the default mode where the limit is a security control.

        PARALLELISM TRADEOFF: the fail-open default trades correctness under
        contention for availability. ``strict=True`` trades a small bounded
        wait (and hard denial on timeout) for a cap that actually holds under
        concurrency. Pick per caller.

        Args:
            strict: If True, fail CLOSED on lock contention / timeout / internal
                    errors (return False, deny). If False (default), fail OPEN.

        Returns:
            bool: True if token consumed successfully, False if rate limit exceeded

        """
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
        """Garbage collect rate limit buckets that haven't been used in 30 days.

        Run this as a scheduled action to prevent table bloat.
        """
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
