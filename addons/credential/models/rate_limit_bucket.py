import hashlib
import logging
from datetime import timedelta
from typing import Any

from psycopg import errors as psycopg_errors

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_REFILL_SECONDS = 3600


class RateLimitBucket(models.Model):
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
        try:
            return self._PERIOD_SECONDS[period]
        except KeyError as exc:
            raise ValueError(
                f"Unknown rate-limit period {period!r} "
                f"(valid: {sorted(self._PERIOD_SECONDS)})"
            ) from exc

    def _get_endpoint_config(self) -> tuple[int, int, float]:
        self.ensure_one()

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

        max_requests = getattr(endpoint, "rate_limit_requests", None)
        if max_requests is None:
            max_requests = 100

        period_seconds = None
        candidate = getattr(endpoint, "rate_limit_window_seconds", None)
        if candidate is not None and candidate > 0:
            period_seconds = candidate
        else:
            period = getattr(endpoint, "rate_limit_period", None) or "minute"
            period_seconds = self._get_period_seconds(period)

        refill_rate = (max_requests / period_seconds) if period_seconds else 0.0

        return max_requests, period_seconds, refill_rate

    @api.model
    def consume_for(
        self,
        endpoint_record: Any,
        company_id: int | None = None,
        strict: bool = False,
    ) -> bool:
        bucket = self.sudo().get_or_create_bucket(endpoint_record, company_id)
        return bucket.consume_token(strict=strict)

    @api.model
    def get_or_create_bucket(
        self,
        endpoint_record: Any,
        company_id: int | None = None,
        bucket_key: str | None = None,
    ) -> Any:
        company_part = company_id or "global"
        bucket_key = (
            bucket_key or f"{endpoint_record._name}:{endpoint_record.id}:{company_part}"
        )

        bucket = self.search([("bucket_key", "=", bucket_key)], limit=1)
        if bucket:
            return bucket

        max_requests = getattr(endpoint_record, "rate_limit_requests", None)
        if max_requests is None:
            max_requests = 100

        savepoint = (
            f"bucket_create_{hashlib.sha256(bucket_key.encode()).hexdigest()[:16]}"
        )
        self.env.cr.execute(f'SAVEPOINT "{savepoint}"')
        try:
            bucket = self.create(
                {
                    "bucket_key": bucket_key,
                    "endpoint_model": endpoint_record._name,
                    "endpoint_id": endpoint_record.id,
                    "company_id": company_id,
                    "tokens": max_requests,
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
                raise
            return bucket

    STRICT_LOCK_TIMEOUT_MS = 3000

    def _lock_bucket_row(self, strict: bool):
        if not strict:
            self.env.cr.execute(
                """
                SELECT id, tokens, last_refill
                FROM rate_limit_bucket
                WHERE id = %s
                FOR UPDATE SKIP LOCKED
                """,
                [self.id],
            )
            return self.env.cr.fetchone()

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
        row = self.env.cr.fetchone()
        self.env.cr.execute("RESET lock_timeout")
        return row

    def _refilled_tokens(
        self,
        current_tokens,
        last_refill,
        now,
        capacity=None,
        refill_rate=None,
    ):
        if capacity is None or refill_rate is None:
            capacity, _period, refill_rate = self._get_endpoint_config()
        elapsed_seconds = (now - last_refill).total_seconds()

        if elapsed_seconds < 0:
            _logger.warning(
                "Backward clock skew detected for bucket %s: elapsed_seconds=%.2f.",
                self.bucket_key,
                elapsed_seconds,
            )
            return current_tokens

        elapsed_seconds = min(elapsed_seconds, MAX_REFILL_SECONDS)
        return min(current_tokens + elapsed_seconds * refill_rate, capacity)

    def consume_token(
        self,
        strict: bool = False,
        capacity: float | None = None,
        refill_rate: float | None = None,
    ) -> bool:
        self.ensure_one()

        savepoint_name = f"rate_limit_lock_{self.id}"
        self.env.cr.execute(f"SAVEPOINT {savepoint_name}")

        try:
            row = self._lock_bucket_row(strict)
            if not row:
                self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                if strict:
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
            now = fields.Datetime.now()
            new_tokens = self._refilled_tokens(
                current_tokens,
                last_refill,
                now,
                capacity=capacity,
                refill_rate=refill_rate,
            )

            if new_tokens >= 1.0:
                final_tokens = new_tokens - 1.0

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
                self.invalidate_recordset(
                    ["tokens", "last_refill", "last_request_at"],
                )
                return True

            _logger.warning(
                "Rate limit EXCEEDED: %s (tokens: %.2f, need: 1.0)",
                self.bucket_key,
                new_tokens,
            )
            self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            return False

        except Exception as e:
            self.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")

            if strict:
                _logger.error(
                    "Error consuming token from bucket %s: %s. Denying request (strict mode).",
                    self.bucket_key,
                    e,
                )
                return False

            _logger.error(
                "Error consuming token from bucket %s: %s. Allowing request to prevent user-facing errors.",
                self.bucket_key,
                e,
            )
            return True

    def reset_bucket(self) -> None:
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
