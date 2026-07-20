"""Credential Access Rate Limiter for preventing credential harvesting attacks.

Provides sliding window rate limiting to prevent:
- Credential harvesting attacks
- Brute force decryption attempts
- Excessive credential access attempts

Thread-safe, registry-based, automatic cleanup.

NOTE: This is for credential access rate limiting.
For HTTP endpoint rate limiting, see endpoint_rate_limiter.py
"""

import logging
import threading
from collections import OrderedDict
from datetime import timedelta

from odoo import fields
from odoo.tools import config

_logger = logging.getLogger(__name__)


class CredentialAccessRateLimiter:
    """Sliding window rate limiter for credential operations.

    Tracks access attempts per (credential_id, user_id, operation) tuple, is
    thread-safe, and evicts least-recently-used keys once max_keys is reached
    to bound memory against exhaustion attacks.
    """

    # Maximum number of unique keys to track (prevents memory exhaustion)
    DEFAULT_MAX_KEYS = 10000

    def __init__(self, max_keys: int = DEFAULT_MAX_KEYS):
        """Initialize the rate limiter.

        :param int max_keys: maximum number of unique (credential, user,
            operation) tuples to track; oldest entries are evicted when the
            limit is reached. Default 10000 keys (~1-5MB depending on window).
        """
        # OrderedDict gives O(1) LRU eviction via popitem(last=False). The
        # previous implementation used a plain defaultdict(list) plus a linear
        # scan to find the oldest-most-recent-timestamp, which was O(n * m)
        # per eviction (n = number of keys, m = timestamps per key).
        # Key layout: (cred_id, user_id, operation) -> list of timestamps.
        self._attempts: OrderedDict[tuple, list] = OrderedDict()
        self._lock = threading.RLock()
        self._max_keys = max_keys
        _logger.info(
            "RateLimiter initialized with max_keys=%d",
            max_keys,
        )

    def check_rate_limit(
        self,
        credential_id,
        user_id,
        operation="read",
        limit=100,
        window_minutes=60,
    ):
        """Check whether the sliding-window rate limit has been exceeded.

        Only counts attempts within the time window.

        :param int credential_id: credential record ID
        :param int user_id: user record ID
        :param str operation: operation type (read, write, etc.)
        :param int limit: maximum attempts allowed in the window
        :param int window_minutes: time window in minutes
        :return: result with keys ``allowed``, ``attempts``, ``limit``,
            ``window_minutes`` and ``reset_at`` (when the window resets)
        :rtype: dict
        """
        with self._lock:
            key = (credential_id, user_id, operation)
            now = fields.Datetime.now()
            window_start = now - timedelta(minutes=window_minutes)

            # Explicit .get() — OrderedDict doesn't auto-insert on lookup
            # (defaultdict did, which was the source of a prior eviction bug).
            existing = self._attempts.get(key, [])

            # Remove attempts outside the window (cleanup)
            filtered = [ts for ts in existing if ts > window_start]

            current_attempts = len(filtered)
            allowed = current_attempts < limit

            if allowed:
                key_is_new = key not in self._attempts
                # Evict oldest key BEFORE inserting a new one (prevents memory
                # exhaustion). Must be a >= check on capacity: at exactly
                # max_keys we must evict before adding one more.
                if key_is_new and len(self._attempts) >= self._max_keys:
                    self._evict_oldest_key()

                filtered.append(now)
                current_attempts += 1

            # Write back and bump the LRU position. If the bucket is empty
            # (all timestamps aged out and the caller was denied), drop the
            # key entirely so the tracked set doesn't grow unbounded.
            if filtered:
                self._attempts[key] = filtered
                # move_to_end marks this key as most-recently-used, which is
                # exactly what popitem(last=False) in _evict_oldest_key relies
                # on when the limiter is full.
                self._attempts.move_to_end(key)
            elif key in self._attempts:
                del self._attempts[key]

            # Calculate when window resets (oldest timestamp + window)
            reset_at = None
            if filtered:
                oldest = min(filtered)
                reset_at = oldest + timedelta(minutes=window_minutes)

            result = {
                "allowed": allowed,
                "attempts": current_attempts,
                "limit": limit,
                "window_minutes": window_minutes,
                "reset_at": reset_at,
            }

            if not allowed:
                _logger.warning(
                    "Rate limit exceeded for credential %s, user %s, operation %s: %s/%s in %s minutes",
                    credential_id,
                    user_id,
                    operation,
                    current_attempts,
                    limit,
                    window_minutes,
                )

            return result

    def _evict_oldest_key(self):
        """Evict the least-recently-used key to bound memory.

        Called when max_keys is reached. Must be called while holding self._lock.
        """
        if not self._attempts:
            return

        # popitem(last=False) is O(1) and pops the LRU key, thanks to the
        # move_to_end that check_rate_limit runs on every successful record.
        # The previous implementation scanned all keys (O(n * m)) to find it.
        oldest_key, _timestamps = self._attempts.popitem(last=False)
        _logger.debug(
            "Rate limiter evicted LRU key %s (max_keys=%d reached)",
            oldest_key,
            self._max_keys,
        )

    def reset_limit(self, credential_id, user_id, operation="read"):
        """Reset the rate limit for a specific key.

        :param int credential_id: credential record ID
        :param int user_id: user record ID
        :param str operation: operation type
        """
        with self._lock:
            key = (credential_id, user_id, operation)
            if key in self._attempts:
                del self._attempts[key]
                _logger.info(
                    "Rate limit reset for credential %s, user %s, operation %s",
                    credential_id,
                    user_id,
                    operation,
                )

    def get_stats(self):
        """Return rate limiter statistics.

        :return: stats with keys ``total_keys``, ``max_keys``,
            ``total_attempts_tracked`` and ``memory_usage_pct``
        :rtype: dict
        """
        with self._lock:
            total_attempts = sum(len(attempts) for attempts in self._attempts.values())
            total_keys = len(self._attempts)
            return {
                "total_keys": total_keys,
                "max_keys": self._max_keys,
                "total_attempts_tracked": total_attempts,
                "memory_usage_pct": (
                    (total_keys / self._max_keys * 100) if self._max_keys > 0 else 0.0
                ),
            }

    def cleanup_old_entries(self, max_age_hours=24):
        """Remove entries older than the given age.

        Called periodically (cron) to prevent memory bloat.

        :param int max_age_hours: remove entries older than this many hours
        :return: number of keys removed
        :rtype: int
        """
        with self._lock:
            cutoff = fields.Datetime.now() - timedelta(hours=max_age_hours)
            keys_to_remove = []

            for key, attempts in self._attempts.items():
                # Remove old timestamps
                self._attempts[key] = [ts for ts in attempts if ts > cutoff]

                # If no attempts left, mark key for removal
                if not self._attempts[key]:
                    keys_to_remove.append(key)

            # Remove empty keys
            for key in keys_to_remove:
                del self._attempts[key]

            if keys_to_remove:
                _logger.info(
                    "Rate limiter cleanup: removed %d empty keys",
                    len(keys_to_remove),
                )

            return len(keys_to_remove)


# ==================== Registry-Based Credential Access Rate Limiter ====================


def get_credential_rate_limiter(env):
    """Get or create credential access rate limiter from registry.

    ⚠️ IMPORTANT — per-worker, not per-database.
    An Odoo ``Registry`` lives in one Python process. In threading mode
    (``workers = 0``) all threads share one registry, so the limit is
    process-wide. In prefork mode (``workers >= 1``) EACH worker has its
    own ``Registry`` and its own limiter instance, so the effective
    cluster-wide limit is ``limit x num_workers``. If you need a hard
    cluster-wide cap, route through ``rate.limit.bucket`` (DB-backed token
    bucket) instead.

    Registry storage still gives us:
    - Automatic cleanup on module upgrade (registry rebuild)
    - Thread-safe access within a single worker
    """
    registry = env.registry

    if not hasattr(registry, "_credential_access_rate_limiter"):
        registry._credential_access_rate_limiter = CredentialAccessRateLimiter()
        # Emitted once per worker on first limiter use. In prefork mode this
        # will fire N times (once per worker) which is the point — operators
        # should see exactly how many independent limiters exist.
        workers = config.get("workers", 0) or 0
        if workers >= 1:
            _logger.warning(
                "Credential access rate limiter is per-worker: effective "
                "cluster-wide limit is (per-credential limit) x %d workers. "
                "Database '%s'. For a hard cluster-wide cap, route through "
                "rate.limit.bucket instead.",
                workers,
                env.cr.dbname,
            )
        else:
            _logger.info(
                "Created credential access rate limiter for worker (database '%s', threading mode)",
                env.cr.dbname,
            )

    return registry._credential_access_rate_limiter
