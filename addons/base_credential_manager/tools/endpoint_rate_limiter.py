"""Generic database-backed token bucket rate limiter for HTTP endpoints.

Works with any model that exposes rate limiting configuration fields. For
credential access rate limiting, see ``rate_limiter.py``.
"""

import logging
from typing import Any

_logger = logging.getLogger(__name__)


class EndpointRateLimiter:
    """Generic database-backed token bucket rate limiter.

    Works with any Odoo model that exposes these fields:

    - ``rate_limit_enabled`` (Boolean) -- preferred, used by
      ``api.channel.mixin`` and every model that inherits it
      (``api.endpoint.outbound``, …).
    - ``enable_rate_limiting`` (Boolean) -- legacy alias still used by
      ``telegram.chat`` and other pre-mixin models, accepted for
      backward compatibility.
    - ``rate_limit_requests`` (Integer)
    - ``rate_limit_period`` (Selection: 'second', 'minute', 'hour', 'day')
    """

    def __init__(self, env: Any, endpoint: Any, company_id: int | None = None) -> None:
        """Initialize the rate limiter.

        :param env: Odoo environment
        :param endpoint: record with rate limit fields (any model)
        :param company_id: company id for per-company limits (optional)
        """
        self.env = env
        self.endpoint = endpoint
        self.company_id = company_id

    def check_limit(self) -> bool:
        """Check whether the request is within rate limits.

        :return: True if the request is allowed, False if the limit is exceeded
        :rtype: bool
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

        # A truthy ``rate_limit_strict`` field runs the bucket fail-closed
        # (errors/contention deny the request). Default is fail-open (webhook
        # semantics).
        strict = bool(getattr(self.endpoint, "rate_limit_strict", False))

        # Get or create token bucket
        bucket_model = self.env["rate.limit.bucket"].sudo()
        bucket = bucket_model.get_or_create_bucket(self.endpoint, self.company_id)

        # Consume one token atomically. The bucket row is shared across
        # workers and locked with SELECT FOR UPDATE SKIP LOCKED, so this stays
        # correct in multi-worker, multi-server deployments.
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
    """Create an :class:`EndpointRateLimiter` instance.

    :param env: Odoo environment
    :param endpoint: record with rate limit fields
    :param company_id: company id for per-company limits (optional)
    :return: endpoint rate limiter instance
    :rtype: EndpointRateLimiter
    """
    return EndpointRateLimiter(env, endpoint, company_id)
