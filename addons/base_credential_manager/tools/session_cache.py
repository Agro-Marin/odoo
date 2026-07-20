"""Session Cache for HTTP session/connection reuse.

Provides thread-safe LRU caching with TTL for session objects. Registry-based
storage ensures automatic cleanup on module upgrade.
"""

import logging
from collections.abc import Callable
from typing import Any

from .base_lru_cache import BaseLRUCache

_logger = logging.getLogger(__name__)


class SessionCache(BaseLRUCache):
    """Thread-safe LRU cache for sessions with TTL.

    Default-enable TTL expiration and expose a simple get/set API for session
    objects on top of BaseLRUCache. Do not instantiate directly — use
    get_session_cache(env) to retrieve the registry-based instance.
    """

    def __init__(self, max_size: int = 100, ttl_hours: float = 1):
        """Initialize LRU session cache.

        :param max_size: maximum number of sessions to cache
        :param ttl_hours: time-to-live in hours for cached sessions
        """
        # Use reentrant lock because get() calls _touch()/_remove() which also acquire lock
        super().__init__(
            max_size=max_size, ttl_hours=ttl_hours, use_reentrant_lock=True
        )
        _logger.info(
            "SessionCache initialized: max_size=%d, ttl=%.1fh",
            max_size,
            ttl_hours,
        )

    def get(self, key: str) -> Any | None:
        """Get session from cache.

        :param key: cache key
        :return: cached session object, or None if not found/expired
        """
        with self._lock:
            entry = self._get_entry(key)
            if entry is None:
                return None

            # Check expiration
            if self._is_expired(entry):
                _logger.debug("Session cache expired: %s", key)
                self._remove(key)
                return None

            # Update LRU position
            self._touch(key)
            _logger.debug("Session cache hit: %s", key)
            return entry["value"]

    def set(self, key: str, session: Any) -> None:
        """Store session in cache.

        :param key: cache key
        :param session: session object to cache
        """
        evicted = self._set_entry(key, session)
        if evicted:
            _logger.debug("Session cache evicted oldest entry (size: %d)", len(self))
        _logger.debug("Session cached: %s (size: %d)", key, len(self))

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cache entry or entire cache.

        :param key: specific key to invalidate; if None, clears entire cache
        """
        if key is None:
            entries = self._clear()
            _logger.info("Session cache cleared: %d entries removed", len(entries))
        elif self._remove(key):
            _logger.debug("Session cache invalidated: %s", key)

    def invalidate_matching(self, filter_func: Callable[[str], bool]) -> int:
        """Invalidate cache entries matching a filter condition.

        :param filter_func: predicate taking a cache key; return True to invalidate
        :return: number of entries invalidated
        :rtype: int
        """
        # Public API for selective invalidation — use instead of touching _cache.
        removed = self._invalidate_matching(filter_func)
        return len(removed)


# ==================== Registry-Based Cache ====================


def get_session_cache(env, max_size: int = 100, ttl_hours: float = 1) -> SessionCache:
    """Get or create the session cache from the registry."""
    # Per-worker, not per-database: in prefork mode (workers >= 1) each worker has
    # its own Registry and its own cache, so effective hit rate is at most
    # 1 / num_workers. Acceptable for a pure session cache (worst case: redundant
    # logins), but not a global deduplication layer. Registry storage still buys
    # automatic cleanup on module upgrade/reload and thread-safe access within a
    # single worker.
    registry = env.registry

    if not hasattr(registry, "_session_cache"):
        # max_size / ttl_hours only take effect here, on the call that CREATES the
        # cache; later callers get the existing instance unchanged.
        registry._session_cache = SessionCache(max_size=max_size, ttl_hours=ttl_hours)
        _logger.info(
            "Created new session cache for database '%s': max_size=%d, ttl=%.1fh",
            env.cr.dbname,
            max_size,
            ttl_hours,
        )

    return registry._session_cache


def invalidate_session_cache(env) -> None:
    """Invalidate the session cache for the current database.

    :param env: Odoo environment
    """
    registry = env.registry

    # Registry rebuilds (module upgrade) drop the cache automatically; call this
    # for manual invalidation such as credential rotation.
    if hasattr(registry, "_session_cache"):
        cache = registry._session_cache
        stats = cache.get_stats()
        cache.invalidate()
        _logger.info(
            "Manually invalidated session cache for database '%s': %d entries removed",
            env.cr.dbname,
            stats["size"],
        )
