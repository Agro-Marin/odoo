"""Generic rate limiter for HTTP endpoints (webhooks, APIs, etc.).

Database-backed token bucket algorithm that works with any model
having rate limiting configuration fields.

This is the HTTP endpoint rate limiter - for credential access rate limiting,
see credential_access_rate_limiter.py
"""

import logging
from typing import Any

_logger = logging.getLogger(__name__)


class EndpointRateLimiter:
    """Generic database-backed rate limiter using token bucket algorithm.

    Works with any Odoo model that has these fields:
    - ``rate_limit_enabled`` (Boolean) -- preferred, used by
      ``api.channel.mixin`` and every model that inherits it
      (``api.endpoint.outbound``, …).
    - ``enable_rate_limiting`` (Boolean) -- legacy alias still used by
      ``telegram.chat`` and other pre-mixin models. Accepted for
      backward compatibility.
    - rate_limit_requests (Integer)
    - rate_limit_period (Selection: 'second', 'minute', 'hour', 'day')

    Pattern: Token bucket algorithm with SELECT FOR UPDATE SKIP LOCKED.

    Benefits:
    - Database-backed token bucket shared across all workers
    - Atomic token consumption with SELECT FOR UPDATE SKIP LOCKED
    - Works correctly in multi-worker, multi-server deployments
    - No complex caching logic needed

    Usage:
        # For any endpoint with rate limit fields
        limiter = EndpointRateLimiter(env, webhook_subscription)
        if not limiter.check_limit():
            return error_response("Rate limit exceeded")

        # For per-company rate limiting
        limiter = EndpointRateLimiter(env, api_service, company_id=company.id)
        if not limiter.check_limit():
            return error_response("Rate limit exceeded")
    """

    def __init__(self, env: Any, endpoint: Any, company_id: int | None = None) -> None:
        """Initialize EndpointRateLimiter.

        Args:
            env: Odoo environment
            endpoint: Record with rate limit fields (any model)
            company_id: Company ID for per-company limits (optional)

        """
        self.env = env
        self.endpoint = endpoint
        self.company_id = company_id

    def check_limit(self) -> bool:
        """Check if request is within rate limits using database-backed token bucket.

        Returns:
            True if request allowed, False if rate limit exceeded

        Implementation:
        1. Get or create token bucket for this endpoint+company
        2. Attempt to consume 1 token atomically
        3. Token bucket refills automatically based on elapsed time

        If the endpoint model exposes a truthy ``rate_limit_strict`` field,
        the bucket runs in fail-closed mode (errors/contention deny the
        request). Default is fail-open (webhook semantics).

        """
        # Check if rate limiting is enabled.  Two field names exist in
        # the codebase: ``rate_limit_enabled`` (api.channel.mixin and
        # every model that inherits it, including api.endpoint.outbound)
        # and ``enable_rate_limiting`` (legacy telegram.chat field).
        # Accept either so the limiter stays generic.
        enabled = getattr(self.endpoint, "rate_limit_enabled", None)
        if enabled is None:
            enabled = getattr(self.endpoint, "enable_rate_limiting", False)
        if not enabled:
            return True

        strict = bool(getattr(self.endpoint, "rate_limit_strict", False))

        # Get or create token bucket
        bucket_model = self.env["rate.limit.bucket"].sudo()
        bucket = bucket_model.get_or_create_bucket(self.endpoint, self.company_id)

        # Attempt to consume token (atomic operation)
        allowed = bucket.consume_token(strict=strict)

        if not allowed:
            _logger.warning(
                "Rate limit exceeded: model=%s, record_id=%s, company=%s",
                self.endpoint._name,
                self.endpoint.id,
                self.company_id or "global",
            )

        return allowed


def get_endpoint_rate_limiter(
    env: Any, endpoint: Any, company_id: int | None = None
) -> EndpointRateLimiter:
    """Factory function to create EndpointRateLimiter instance.

    Args:
        env: Odoo environment
        endpoint: Record with rate limit fields
        company_id: Company ID for per-company limits (optional)

    Returns:
        Endpoint rate limiter instance

    """
    return EndpointRateLimiter(env, endpoint, company_id)
